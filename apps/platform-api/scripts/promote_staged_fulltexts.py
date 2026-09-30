"""Promote staged, parsed publication PDFs to canonical full-text resources."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from smartlib_platform.publications.incremental import promote_staged_fulltext


def candidates(connection: psycopg.Connection) -> list[dict[str, object]]:
    return connection.execute(
        """SELECT DISTINCT ON (item.matched_publication_id)
                  item.matched_publication_id AS publication_id,item.record_id,
                  pre.preverification_id,pre.file_name,pre.content_checksum,pre.storage_uri,
                  pre.extracted_text_uri,pre.page_count,pre.text_length,pre.extraction_method,
                  pre.match_confidence,pre.match_score
             FROM (smartlib.publication_intake_record item
                  JOIN smartlib.ingestion_record input_record USING(record_id)
                  LEFT JOIN smartlib.representative_work_submission submission USING(record_id))
             JOIN smartlib.publication_fulltext_preverification pre USING (record_id)
            WHERE item.matched_publication_id IS NOT NULL AND pre.storage_state='stored'
              AND pre.preverification_status NOT IN ('conflict','superseded')
              AND NOT EXISTS (
                  SELECT 1 FROM smartlib.publication_fulltext_resource resource
                   WHERE resource.publication_id=item.matched_publication_id
              )
            ORDER BY item.matched_publication_id,pre.match_score DESC,pre.evaluated_at DESC"""
    ).fetchall()


def write_report(path: Path, report: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    actor_id = UUID(
        os.environ.get("SMARTLIB_DEV_ACTOR_ID", "00000000-0000-4000-8000-000000000001")
    )
    started_at = datetime.now(UTC).isoformat()
    results: list[dict[str, object]] = []
    with psycopg.connect(os.environ["SMARTLIB_DATABASE_URL"], row_factory=dict_row) as connection:
        connection.execute("SELECT set_config('smartlib.actor_id', %s, false)", (str(actor_id),))
        connection.commit()
        rows = candidates(connection)
        preflight = {
            "schema_version": "staged-fulltext-promotion-v1",
            "mode": "apply" if args.apply else "dry_run",
            "started_at": started_at,
            "candidate_publications": len(rows),
            "unique_physical_files": len({row["content_checksum"] for row in rows}),
            "candidates": rows,
        }
        write_report(args.report, preflight)
        if not args.apply:
            print(
                json.dumps(
                    {
                        key: preflight[key]
                        for key in ("mode", "candidate_publications", "unique_physical_files")
                    }
                )
            )
            return

        for index, row in enumerate(rows, start=1):
            try:
                with connection.transaction():
                    connection.execute(
                        "SELECT set_config('smartlib.actor_id', %s, true)", (str(actor_id),)
                    )
                    resource_id, created = promote_staged_fulltext(
                        connection,
                        record_id=row["record_id"],
                        publication_id=row["publication_id"],
                        actor_id=actor_id,
                        trace_id="controlled-staged-fulltext-promotion-v1",
                    )
                results.append(
                    {
                        "publication_id": row["publication_id"],
                        "preverification_id": row["preverification_id"],
                        "fulltext_resource_id": resource_id,
                        "status": "created" if created else "reused",
                    }
                )
            except Exception as exc:
                results.append(
                    {
                        "publication_id": row["publication_id"],
                        "preverification_id": row["preverification_id"],
                        "status": "failed",
                        "error": str(exc),
                    }
                )
            preflight["processed"] = index
            preflight["results"] = results
            preflight["updated_at"] = datetime.now(UTC).isoformat()
            write_report(args.report, preflight)

    counts = {
        status: sum(row["status"] == status for row in results)
        for status in ("created", "reused", "failed")
    }
    print(json.dumps({"candidates": len(rows), "counts": counts}))
    if counts["failed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
