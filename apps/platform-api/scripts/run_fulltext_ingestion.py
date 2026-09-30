import argparse
import json
import os
import re
import sys
from datetime import UTC, datetime
from difflib import SequenceMatcher
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from smartlib_platform.fulltext import extract_pdf
from smartlib_platform.publications.incremental import submit_publication_supplement
from smartlib_platform.publications.models import FulltextSupplementInput, PublicationSupplementCreate
from smartlib_platform.storage.s3 import S3ObjectStore, inspect_pdf

RECORD_PATTERN = re.compile(r"NSF-FT-\d{4}")


class IdentityNotReady(ValueError):
    pass


def normalize(value: object) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(value or "").casefold())


def title_score(left: object, right: object) -> float:
    return SequenceMatcher(None, normalize(left), normalize(right)).ratio()


def load_inputs(manifest_path: Path, pdf_directory: Path, verification_path: Path | None) -> list[dict]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    records = {item["record_id"]: item for item in manifest["records"]}
    verified: dict[str, dict] = {}
    if verification_path and verification_path.exists():
        for item in json.loads(verification_path.read_text(encoding="utf-8")).get("records", []):
            if item.get("下载状态") == "成功":
                verified[str(item["记录ID"])] = item
    inputs: list[dict] = []
    for path in sorted(pdf_directory.glob("*.pdf")):
        match = RECORD_PATTERN.search(path.name)
        if not match:
            continue
        record_id = match.group(0)
        if record_id not in records:
            raise ValueError(f"PDF 任务编号不在受控清单中: {record_id}")
        inputs.append({"path": path, "record": records[record_id], "verified": verified.get(record_id)})
    if len({item["record"]["record_id"] for item in inputs}) != len(inputs):
        raise ValueError("PDF 目录存在重复任务编号")
    return inputs


def match_database(connection, record: dict) -> dict:
    row = connection.execute(
        """SELECT record_id,COALESCE((input_record.source_locator->>'row')::integer,
                            (input_record.source_locator->>'position')::integer) AS source_row_number,
                  representative_work_number,awardee_name_raw,
                  normalized_payload,matched_publication_id,verification_state
             FROM (smartlib.publication_intake_record item
                  JOIN smartlib.ingestion_record input_record USING(record_id)
                  LEFT JOIN smartlib.representative_work_submission submission USING(record_id))
             WHERE COALESCE((input_record.source_locator->>'row')::integer,
                            (input_record.source_locator->>'position')::integer)=%s""",
        (int(record["representative_row"]),),
    ).fetchone()
    if not row:
        raise ValueError("找不到对应的论文导入行")
    score = title_score(record["title"], row["normalized_payload"].get("title"))
    awardee_matches = normalize(record["person"]) == normalize(row["awardee_name_raw"])
    if not awardee_matches or score < 0.92:
        raise ValueError(f"清单与数据库身份核验失败: awardee={awardee_matches}, title={score:.3f}")
    if row["matched_publication_id"] is None:
        raise IdentityNotReady(f"论文身份尚未确认: {row['verification_state']}")
    return {**dict(row), "title_score": round(score, 4), "awardee_matches": awardee_matches}


def report_write(path: Path, started_at: str, results: list[dict]) -> None:
    counts: dict[str, int] = {}
    for item in results:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schema_version": "smartlib-fulltext-ingestion-report-v1",
        "started_at": started_at,
        "updated_at": datetime.now(UTC).isoformat(),
        "counts": counts,
        "records": results,
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="受控论文全文批量匹配、上传与解析")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--pdf-directory", type=Path, required=True)
    parser.add_argument("--verification", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--mode", choices=["match", "ingest"], default="match")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--record-id", action="append", default=[])
    args = parser.parse_args()
    if args.apply and args.mode != "ingest":
        parser.error("--apply 只能与 --mode ingest 一起使用")

    database_url = os.environ["SMARTLIB_DATABASE_URL"]
    actor_id = UUID(os.environ.get("SMARTLIB_DEV_ACTOR_ID", "00000000-0000-4000-8000-000000000001"))
    maximum = int(os.environ.get("SMARTLIB_BATCH_FULLTEXT_MAX_BYTES", str(350 * 1024 * 1024)))
    store = S3ObjectStore(
        os.environ.get("SMARTLIB_S3_ENDPOINT_URL", "http://minio:9000"),
        os.environ.get("SMARTLIB_S3_BUCKET", "smartlib-publications"),
        os.environ["SMARTLIB_S3_ACCESS_KEY"], os.environ["SMARTLIB_S3_SECRET_KEY"],
        os.environ.get("SMARTLIB_S3_REGION", "us-east-1"),
    )
    inputs = load_inputs(args.manifest, args.pdf_directory, args.verification)
    if args.record_id:
        selected = set(args.record_id)
        inputs = [item for item in inputs if item["record"]["record_id"] in selected]
    if args.limit:
        inputs = inputs[:args.limit]

    started_at = datetime.now(UTC).isoformat()
    results: list[dict] = []
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        for index, item in enumerate(inputs, start=1):
            record, path = item["record"], item["path"]
            outcome = {"record_id": record["record_id"], "file_name": path.name,
                       "source_row_number": record["representative_row"]}
            try:
                with connection.transaction():
                    connection.execute("SELECT set_config('smartlib.actor_id', %s, true)", (str(actor_id),))
                    matched = match_database(connection, record)
                outcome.update({
                    "publication_id": str(matched["matched_publication_id"]),
                    "title_score": matched["title_score"],
                    "match_basis": "task_id+source_row+awardee+title",
                })
                if args.mode == "match":
                    outcome["status"] = "matched"
                else:
                    with path.open("rb") as stream:
                        prepared = inspect_pdf(stream, path.name, maximum)
                    expected = (item["verified"] or {}).get("SHA256") or record.get("pdf_sha256")
                    if expected and expected.lower() != prepared.content_checksum.lower():
                        raise ValueError("PDF SHA-256 与受控下载清单不一致")
                    extraction = extract_pdf(path)
                    if not args.apply:
                        outcome.update({"status": "ready", "checksum": prepared.content_checksum,
                                        "page_count": extraction.page_count,
                                        "text_length": len(extraction.text),
                                        "extraction_method": extraction.method})
                    else:
                        publication_id = UUID(str(matched["matched_publication_id"]))
                        created_objects = []
                        try:
                            with path.open("rb") as stream:
                                fulltext_object = store.put_fulltext(publication_id, prepared, stream)
                            if fulltext_object.created and fulltext_object.version_id:
                                created_objects.append(fulltext_object)
                            text_key = (f"publications/{publication_id}/derived/"
                                        f"{prepared.content_checksum}/fulltext.txt")
                            text_object = store.put_bytes(text_key, extraction.text.encode("utf-8"),
                                                          "text/plain; charset=utf-8")
                            if text_object.created and text_object.version_id:
                                created_objects.append(text_object)
                            structural = dict(extraction.metadata)
                            structural["extracted_text_uri"] = text_object.storage_uri
                            enrich = {"fulltext_extraction": structural}
                            if structural.get("abstract"):
                                enrich["abstract"] = structural["abstract"]
                            if structural.get("keywords"):
                                enrich["keywords"] = structural["keywords"]
                            command = PublicationSupplementCreate(
                                source_kind="fulltext",
                                source_label="2026国自然代表性论著批量全文",
                                source_uri=fulltext_object.storage_uri,
                                content_checksum=prepared.content_checksum,
                                fulltext=FulltextSupplementInput(
                                    file_name=prepared.file_name,
                                    storage_uri=fulltext_object.storage_uri,
                                    content_checksum=prepared.content_checksum,
                                    size_bytes=prepared.size_bytes,
                                    license_tags=["controlled-fulltext", "batch-ingested"],
                                    extraction_state="extracted",
                                    extracted_metadata=enrich,
                                ),
                                note=(f"{record['record_id']}; 匹配依据: 任务编号、源行、获批人和题名; "
                                      f"题名相似度 {matched['title_score']:.3f}"),
                            )
                            with connection.transaction():
                                connection.execute("SELECT set_config('smartlib.actor_id', %s, true)",
                                                   (str(actor_id),))
                                supplement = submit_publication_supplement(
                                    connection, publication_id, command, actor_id, f"fulltext-batch-{uuid4()}"
                                )
                                connection.execute(
                                    """UPDATE smartlib.publication_fulltext_resource SET
                                           extraction_method=%s,extraction_version=%s,extracted_text_uri=%s,
                                           page_count=%s,text_length=%s,ocr_page_count=%s,
                                           extracted_metadata=%s,extracted_at=clock_timestamp(),
                                           extraction_error=NULL
                                         WHERE publication_id=%s AND content_checksum=%s""",
                                    (extraction.method, "publication-fulltext-extraction-v1",
                                     text_object.storage_uri, extraction.page_count, len(extraction.text),
                                     extraction.ocr_page_count, Jsonb(enrich), publication_id,
                                     prepared.content_checksum),
                                )
                            outcome.update({"status": "ingested",
                                            "submission_id": str(supplement.submission_id),
                                            "checksum": prepared.content_checksum,
                                            "storage_uri": fulltext_object.storage_uri,
                                            "text_storage_uri": text_object.storage_uri,
                                            "page_count": extraction.page_count,
                                            "text_length": len(extraction.text),
                                            "extraction_method": extraction.method,
                                            "ocr_page_count": extraction.ocr_page_count})
                        except Exception:
                            for stored in reversed(created_objects):
                                store.delete_version(stored.object_key, stored.version_id)
                            raise
            except IdentityNotReady as exc:
                connection.rollback()
                outcome.update({"status": "blocked", "error": str(exc)})
            except Exception as exc:
                connection.rollback()
                outcome.update({"status": "failed", "error": str(exc)})
            results.append(outcome)
            report_write(args.report, started_at, results)
            print(f"[{index}/{len(inputs)}] {record['record_id']}: {outcome['status']}", flush=True)
    report_write(args.report, started_at, results)
    failed = sum(item["status"] == "failed" for item in results)
    summary = {"total": len(results), "failed": failed, "report": str(args.report)}
    print(json.dumps(summary, ensure_ascii=False))
    if failed:
        sys.exit(2)


if __name__ == "__main__":
    main()
