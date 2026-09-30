"""Stage archive-discovered publication PDFs and text derivatives in object storage."""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from smartlib_platform.fulltext import extract_pdf
from smartlib_platform.storage.s3 import (
    S3ObjectStore,
    inspect_pdf,
    staged_fulltext_key,
    staged_text_key,
)

RULE_VERSION = "archive-fulltext-object-staging-v1"


def resolve_path(reported: str, reported_root: Path, archive_root: Path) -> Path:
    return archive_root / Path(reported).relative_to(reported_root)


def verify_object_size(store: S3ObjectStore, key: str, expected: int) -> None:
    headers = store.head_object(key)
    if headers is None:
        raise RuntimeError("对象写入后无法读取")
    actual = headers.get("content-length")
    if actual is not None and int(actual) != expected:
        raise RuntimeError(f"对象大小核验失败: expected={expected}, actual={actual}")


def write_report(path: Path, started_at: str, results: list[dict[str, Any]]) -> None:
    counts = Counter(value["status"] for value in results)
    unique_checksums = {value["checksum"] for value in results if value.get("checksum")}
    created_pdfs = {
        value["checksum"] for value in results if value.get("pdf_object_created") is True
    }
    reused_pdfs = {
        value["checksum"] for value in results if value.get("pdf_object_created") is False
    }
    report = {
        "schema_version": RULE_VERSION,
        "started_at": started_at,
        "updated_at": datetime.now(UTC).isoformat(),
        "counts": dict(counts),
        "record_count": len(results),
        "unique_fulltext_count": len(unique_checksums),
        "unique_pdf_objects_created": len(created_pdfs),
        "unique_pdf_objects_reused": len(reused_pdfs - created_pdfs),
        "records": results,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="将档案扫描命中的论文全文暂存至MinIO")
    parser.add_argument("--matches", type=Path, required=True)
    parser.add_argument("--reported-root", type=Path, required=True)
    parser.add_argument("--archive-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    actor_id = UUID(
        os.environ.get("SMARTLIB_DEV_ACTOR_ID", "00000000-0000-4000-8000-000000000001")
    )
    maximum = int(os.environ.get("SMARTLIB_BATCH_FULLTEXT_MAX_BYTES", str(350 * 1024 * 1024)))
    store = S3ObjectStore(
        os.environ.get("SMARTLIB_S3_ENDPOINT_URL", "http://minio:9000"),
        os.environ.get("SMARTLIB_S3_BUCKET", "smartlib-publications"),
        os.environ["SMARTLIB_S3_ACCESS_KEY"],
        os.environ["SMARTLIB_S3_SECRET_KEY"],
        os.environ.get("SMARTLIB_S3_REGION", "us-east-1"),
    )
    matches = json.loads(args.matches.read_text(encoding="utf-8"))
    if args.limit:
        matches = matches[: args.limit]
    started_at = datetime.now(UTC).isoformat()
    results: list[dict[str, Any]] = []
    staged: dict[str, dict[str, Any]] = {}

    with psycopg.connect(os.environ["SMARTLIB_DATABASE_URL"], row_factory=dict_row) as connection:
        connection.execute("SELECT set_config('smartlib.actor_id', %s, false)", (str(actor_id),))
        connection.commit()
        for index, match in enumerate(matches, start=1):
            outcome: dict[str, Any] = {
                "source_row_number": match["source_row_number"],
                "file_name": match["file_name"],
            }
            try:
                row = connection.execute(
                    """SELECT pre.preverification_id,pre.record_id,pre.preverification_status
                         FROM smartlib.publication_fulltext_preverification pre
                         JOIN (smartlib.publication_intake_record item
                  JOIN smartlib.ingestion_record input_record USING(record_id)
                  LEFT JOIN smartlib.representative_work_submission submission USING(record_id))
                         USING(record_id)
                        WHERE COALESCE((input_record.source_locator->>'row')::integer,
                            (input_record.source_locator->>'position')::integer)=%s
                          AND pre.content_checksum=%s
                          AND pre.preverification_status IN ('ready','review_required')""",
                    (match["source_row_number"], match["sha256"]),
                ).fetchone()
                if not row:
                    raise ValueError("未找到对应的当前全文预核验记录")
                path = resolve_path(match["archive_path"], args.reported_root, args.archive_root)
                with path.open("rb") as stream:
                    prepared = inspect_pdf(stream, path.name, maximum)
                if prepared.content_checksum.lower() != str(match["sha256"]).lower():
                    raise ValueError("本地全文SHA-256与发现报告不一致")

                cached = staged.get(prepared.content_checksum)
                if cached is None:
                    extraction = extract_pdf(path)
                    pdf_key = staged_fulltext_key(prepared.content_checksum)
                    text_key = staged_text_key(prepared.content_checksum)
                    cached = {
                        "checksum": prepared.content_checksum,
                        "pdf_key": pdf_key,
                        "text_key": text_key,
                        "storage_uri": f"s3://{store.bucket}/{pdf_key}",
                        "text_storage_uri": f"s3://{store.bucket}/{text_key}",
                        "page_count": extraction.page_count,
                        "text_length": len(extraction.text),
                        "extraction_method": extraction.method,
                        "ocr_page_count": extraction.ocr_page_count,
                    }
                    if args.apply:
                        with path.open("rb") as stream:
                            pdf_object = store.put_prepared(pdf_key, prepared, stream)
                        text_bytes = extraction.text.encode("utf-8")
                        text_object = store.put_bytes(text_key, text_bytes, "text/plain; charset=utf-8")
                        verify_object_size(store, pdf_key, prepared.size_bytes)
                        verify_object_size(store, text_key, len(text_bytes))
                        cached.update(
                            {
                                "pdf_object_created": pdf_object.created,
                                "pdf_version_id": pdf_object.version_id,
                                "text_object_created": text_object.created,
                            }
                        )
                    staged[prepared.content_checksum] = cached

                outcome.update(cached)
                outcome["preverification_status"] = row["preverification_status"]
                if args.apply:
                    with connection.transaction():
                        connection.execute(
                            "SELECT set_config('smartlib.actor_id', %s, true)", (str(actor_id),)
                        )
                        connection.execute(
                            """UPDATE smartlib.publication_fulltext_preverification SET
                                   storage_state='stored',storage_uri=%s,storage_object_key=%s,
                                   storage_version_id=%s,extracted_text_uri=%s,
                                   stored_at=clock_timestamp(),storage_error=NULL,
                                   page_count=%s,text_length=%s,extraction_method=%s
                                 WHERE preverification_id=%s""",
                            (
                                cached["storage_uri"],
                                cached["pdf_key"],
                                cached.get("pdf_version_id"),
                                cached["text_storage_uri"],
                                cached["page_count"],
                                cached["text_length"],
                                cached["extraction_method"],
                                row["preverification_id"],
                            ),
                        )
                    outcome["status"] = "stored"
                else:
                    outcome["status"] = "ready"
            except Exception as exc:
                connection.rollback()
                outcome.update({"status": "failed", "error": str(exc)})
            results.append(outcome)
            write_report(args.report, started_at, results)
            print(f"[{index}/{len(matches)}] row {match['source_row_number']}: {outcome['status']}",
                  flush=True)

        if args.apply and results:
            counts = Counter(value["status"] for value in results)
            with connection.transaction():
                connection.execute("SELECT set_config('smartlib.actor_id', %s, true)", (str(actor_id),))
                connection.execute(
                    """INSERT INTO audit.audit_event
                              (actor_id,action,resource_type,resource_id,decision,trace_id,details)
                       VALUES (%s,'publication.fulltext.archive_staged','ingestion_batch',
                               '2026-nsf-representative-publications-v1','recorded',%s,%s)""",
                    (
                        actor_id,
                        RULE_VERSION,
                        Jsonb(
                            {
                                "record_count": len(results),
                                "unique_fulltext_count": len(staged),
                                "status_counts": dict(counts),
                            }
                        ),
                    ),
                )

    write_report(args.report, started_at, results)
    print(
        json.dumps(
            {
                "record_count": len(results),
                "unique_fulltext_count": len(staged),
                "counts": dict(Counter(value["status"] for value in results)),
            },
            ensure_ascii=False,
        )
    )
    if any(value["status"] == "failed" for value in results):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
