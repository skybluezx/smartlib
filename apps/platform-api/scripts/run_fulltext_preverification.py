"""Apply pre-ingestion verification evidence from discovered publication PDFs."""

# ruff: noqa: RUF001

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid5

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from smartlib_platform.publications.verification_state import refresh_effective_verification_state

RULE_VERSION = "publication-fulltext-preverification-v1"
NAMESPACE = UUID("21348837-189a-44aa-8da8-f504aec6b832")


def normalized(value: object) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(value or "").casefold())


def reason_number(reasons: list[str], prefix: str) -> float | None:
    for reason in reasons:
        if reason.startswith(prefix + ":"):
            try:
                return float(reason.split(":", 1)[1])
            except ValueError:
                return None
    return None


def checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_path(reported: str, reported_root: Path, archive_root: Path) -> Path:
    relative = Path(reported).relative_to(reported_root)
    return archive_root / relative


def check(code: str, label: str, status: str, source: object, fulltext: object, reason: str) -> dict:
    return {
        "code": code, "label": label, "status": status,
        "source_value": source, "fulltext_value": fulltext, "reason": reason,
    }


def evaluate(match: dict, source: dict, shared_rows: list[int]) -> dict:
    reasons = list(match.get("match_reasons") or [])
    first_dois = [str(value).lower() for value in match.get("first_pages_dois") or []]
    source_doi = str(source.get("doi") or "").lower() or None
    source_year = source.get("publication_year")
    title_exact = "title_exact_in_text" in reasons
    serial_exact = "sci_serial_exact" in reasons
    author_hits = int(reason_number(reasons, "author_hits") or 0)
    fragment_coverage = reason_number(reasons, "title_fragment_coverage") or 0
    fuzzy = reason_number(reasons, "title_fuzzy") or 0

    proposed_doi = source_doi
    if not proposed_doi and len(first_dois) == 1:
        proposed_doi = first_dois[0]
    pdf_title = str(match.get("pdf_title") or "").strip()
    source_title = str(source.get("title") or "").strip()
    proposed_title = source_title
    if (
        len(normalized(source_title)) < 18
        and len(normalized(pdf_title)) >= 18
        and pdf_title.casefold() != "untitled"
    ):
        proposed_title = pdf_title

    checks = [
        check("checksum_integrity", "文件完整性", "passed", match["sha256"], match["sha256"],
              "实际文件SHA-256与发现报告一致"),
    ]
    if title_exact:
        title_status, title_reason = "passed", "全文首页包含规范化后的完整来源题名"
    elif serial_exact and author_hits and "year_present" in reasons:
        title_status, title_reason = "passed", "SCI序号、作者和年份共同一致，双栏版式造成题名断行"
    elif fuzzy >= 0.95 and fragment_coverage >= 0.85 and author_hits:
        title_status, title_reason = "passed", "PDF元数据题名、正文片段和作者共同一致"
    else:
        title_status, title_reason = "review_required", "题名仅达到候选阈值，需要人工查看首页"
    checks.append(check("title_identity", "题名身份一致性", title_status, source_title,
                        proposed_title or pdf_title, title_reason))

    if source_doi and source_doi in first_dois:
        doi_status, doi_reason = "passed", "来源DOI与全文首页DOI一致"
    elif source_doi and first_dois and source_doi not in first_dois:
        doi_status, doi_reason = "conflict", "来源DOI与全文首页检出的DOI冲突"
    elif proposed_doi:
        doi_status, doi_reason = "passed", "从全文首页发现唯一DOI，可作为预核验候选"
    else:
        doi_status, doi_reason = "missing", "来源和全文首页均未提供唯一DOI"
    checks.append(check("identifier_identity", "标识符一致性", doi_status, source_doi,
                        {"doi": proposed_doi, "first_page_dois": first_dois}, doi_reason))

    author_status = "passed" if author_hits else "review_required"
    checks.append(check("awardee_attribution", "作者归属证据", author_status,
                        source.get("authors_raw_list") or [], {"matched_author_count": author_hits},
                        (f"全文首页命中{author_hits}位来源作者" if author_hits else
                         "自动文本匹配未能确认作者，需要人工选择获批人对应作者")))
    if source_year:
        year_status = "passed" if "year_present" in reasons else "review_required"
        year_reason = "全文首页包含来源年份" if year_status == "passed" else "未在首页确认来源年份"
    else:
        year_status, year_reason = "missing", "来源年份缺失，等待外部元数据补采"
    checks.append(check("publication_year", "发表年份", year_status, source_year,
                        source_year if year_status == "passed" else None, year_reason))

    extraction = match.get("fulltext_extraction") or {}
    parse_status = "passed" if extraction.get("state") == "parsed" else "conflict"
    checks.append(check("parse_completeness", "全文解析完整性", parse_status, None, {
        "page_count": extraction.get("page_count"), "text_length": extraction.get("text_length"),
        "method": extraction.get("method"),
    }, "整篇正文已解析" if parse_status == "passed" else "整篇正文解析失败"))

    blocking = [value for value in checks if value["code"] in {
        "checksum_integrity", "title_identity", "awardee_attribution", "parse_completeness"
    }]
    if any(value["status"] == "conflict" for value in checks):
        status = "conflict"
    elif all(value["status"] == "passed" for value in blocking):
        status = "ready"
    else:
        status = "review_required"
    return {
        "status": status,
        "proposed_metadata": {
            "title": proposed_title, "publication_year": source_year,
            "abstract": None, "fulltext_page_count": extraction.get("page_count"),
            "fulltext_text_length": extraction.get("text_length"),
        },
        "proposed_identifiers": {"doi": proposed_doi, "pmid": source.get("pmid"),
                                 "pmcid": source.get("pmcid")},
        "checks": checks,
        "shared_source_rows": shared_rows,
    }


def apply_record(connection, actor_id: UUID, item: dict, match: dict, result: dict) -> None:
    record_id = item["record_id"]
    pre_id = uuid5(NAMESPACE, f"preverification:{record_id}:{match['sha256']}")
    connection.execute(
        """UPDATE smartlib.publication_fulltext_preverification SET preverification_status='superseded'
            WHERE record_id=%s AND content_checksum<>%s
              AND preverification_status NOT IN ('applied','superseded')""",
        (record_id, match["sha256"]),
    )
    connection.execute(
        """INSERT INTO smartlib.publication_fulltext_preverification
                  (preverification_id,record_id,content_checksum,source_path,file_name,size_bytes,
                   page_count,text_length,extraction_method,match_confidence,match_score,
                   preverification_status,proposed_metadata,proposed_identifiers,checks,
                   shared_source_rows,rule_version,evaluated_at,created_by)
             VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
             ON CONFLICT (record_id,content_checksum) DO UPDATE SET
               source_path=excluded.source_path,file_name=excluded.file_name,size_bytes=excluded.size_bytes,
               page_count=excluded.page_count,text_length=excluded.text_length,
               extraction_method=excluded.extraction_method,match_confidence=excluded.match_confidence,
               match_score=excluded.match_score,preverification_status=excluded.preverification_status,
               proposed_metadata=excluded.proposed_metadata,
               proposed_identifiers=excluded.proposed_identifiers,checks=excluded.checks,
               shared_source_rows=excluded.shared_source_rows,rule_version=excluded.rule_version,
               evaluated_at=excluded.evaluated_at""",
        (
            pre_id, record_id, match["sha256"], match["archive_path"], match["file_name"],
            match["size_bytes"], match.get("page_count"),
            (match.get("fulltext_extraction") or {}).get("text_length"),
            (match.get("fulltext_extraction") or {}).get("method"), match["confidence"],
            match["match_score"], result["status"], Jsonb(result["proposed_metadata"]),
            Jsonb(result["proposed_identifiers"]), Jsonb(result["checks"]),
            Jsonb(result["shared_source_rows"]), RULE_VERSION, datetime.now(UTC), actor_id,
        ),
    )
    refresh_effective_verification_state(connection, record_id=record_id)
    groups = {
        "identity": ({"checksum_integrity", "title_identity", "identifier_identity"}, True),
        "attribution": ({"awardee_attribution"}, True),
        "enrichment": ({"publication_year", "parse_completeness"}, False),
    }
    for layer_code, (codes, is_blocking) in groups.items():
        values = [value for value in result["checks"] if value["code"] in codes]
        layer_id = uuid5(NAMESPACE, f"preverification-layer:{record_id}:{layer_code}")
        existing = connection.execute(
            "SELECT layer_id FROM smartlib.publication_verification_layer "
            "WHERE record_id=%s AND layer_code=%s",
            (record_id, layer_code),
        ).fetchone()
        if existing:
            layer_id = existing["layer_id"]
        else:
            connection.execute(
                """INSERT INTO smartlib.publication_verification_layer
                          (layer_id,record_id,layer_code,layer_status,is_blocking,check_count,
                           passed_count,conflict_count,missing_count,rule_version,evidence_summary,
                           evaluated_at,created_by)
                     VALUES (%s,%s,%s,'pending',%s,0,0,0,0,%s,'{}'::jsonb,clock_timestamp(),%s)""",
                (layer_id, record_id, layer_code, is_blocking, RULE_VERSION, actor_id),
            )
        for value in values:
            status = {
                "passed": "passed", "review_required": "pending",
                "conflict": "conflict", "missing": "missing",
            }[value["status"]]
            severity = "blocking" if value["code"] in {
                "checksum_integrity", "title_identity", "awardee_attribution", "parse_completeness"
            } else "warning"
            check_id = uuid5(NAMESPACE, f"preverification-check:{record_id}:{value['code']}")
            connection.execute(
                """INSERT INTO smartlib.publication_verification_check
                          (check_id,layer_id,check_code,check_label,check_status,severity,source_value,
                           authoritative_value,evidence_sources,details,created_by)
                     VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                     ON CONFLICT (layer_id,check_code) DO UPDATE SET
                       check_label=excluded.check_label,check_status=excluded.check_status,
                       severity=excluded.severity,source_value=excluded.source_value,
                       authoritative_value=excluded.authoritative_value,
                       evidence_sources=excluded.evidence_sources,details=excluded.details""",
                (check_id, layer_id, f"fulltext_{value['code']}", value["label"], status, severity,
                 Jsonb(value["source_value"]), Jsonb(value["fulltext_value"]),
                 Jsonb(["local_fulltext_preverification"]),
                 Jsonb({"reason": value["reason"], "rule_version": RULE_VERSION,
                        "preverification_id": str(pre_id)}), actor_id),
            )
    connection.execute(
        """UPDATE smartlib.publication_verification_layer AS layer SET
               check_count=s.total,passed_count=s.passed,conflict_count=s.conflicts,
               missing_count=s.missing,layer_status=CASE
                 WHEN s.blocking_conflicts>0 THEN 'conflict'
                 WHEN s.blocking_open>0 THEN 'incomplete'
                 WHEN layer.layer_code='enrichment' AND s.missing>0 THEN 'incomplete'
                 ELSE 'passed' END,evaluated_at=clock_timestamp()
             FROM (SELECT layer_id,count(*) total,
                          count(*) FILTER (WHERE check_status='passed') passed,
                          count(*) FILTER (WHERE check_status='conflict') conflicts,
                          count(*) FILTER (WHERE check_status IN ('missing','pending')) missing,
                          count(*) FILTER (
                            WHERE severity='blocking' AND check_status='conflict'
                          ) blocking_conflicts,
                          count(*) FILTER (
                            WHERE severity='blocking' AND check_status IN ('missing','pending')
                          ) blocking_open
                     FROM smartlib.publication_verification_check GROUP BY layer_id) s
            WHERE layer.layer_id=s.layer_id AND layer.record_id=%s""",
        (record_id,),
    )
    connection.execute(
        """INSERT INTO audit.audit_event
                  (actor_id,action,resource_type,resource_id,decision,trace_id,details)
             VALUES (%s,'publication.fulltext.preverified','publication_intake_record',%s,
                     'allowed',%s,%s)""",
        (
            actor_id,
            str(record_id),
            RULE_VERSION,
            Jsonb(
                {
                    "preverification_id": str(pre_id),
                    "status": result["status"],
                    "checksum": match["sha256"],
                }
            ),
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="论文全文入库前身份与归属核验")
    parser.add_argument("--matches", type=Path, required=True)
    parser.add_argument("--reported-root", type=Path, required=True)
    parser.add_argument("--archive-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    matches = json.loads(args.matches.read_text(encoding="utf-8"))
    shared: dict[str, list[int]] = defaultdict(list)
    for match in matches:
        shared[match["sha256"]].append(int(match["source_row_number"]))
    outcomes = []
    actor_id = UUID(os.environ.get("SMARTLIB_DEV_ACTOR_ID", "00000000-0000-4000-8000-000000000001"))
    with psycopg.connect(os.environ["SMARTLIB_DATABASE_URL"], row_factory=dict_row) as connection:
        connection.execute("SELECT set_config('smartlib.actor_id', %s, false)", (str(actor_id),))
        connection.commit()
        for match in matches:
            path = resolve_path(match["archive_path"], args.reported_root, args.archive_root)
            outcome = {"source_row_number": match["source_row_number"], "file_name": match["file_name"]}
            try:
                if not path.is_file() or checksum(path) != match["sha256"]:
                    raise ValueError("全文文件不存在或SHA-256与发现报告不一致")
                item = connection.execute(
                    """SELECT record_id,normalized_payload,verification_state,matched_publication_id
                         FROM (smartlib.publication_intake_record item
                  JOIN smartlib.ingestion_record input_record USING(record_id)
                  LEFT JOIN smartlib.representative_work_submission submission USING(record_id))
             WHERE COALESCE((input_record.source_locator->>'row')::integer,
                            (input_record.source_locator->>'position')::integer)=%s""",
                    (match["source_row_number"],),
                ).fetchone()
                if not item:
                    raise ValueError("找不到对应导入记录")
                result = evaluate(match, item["normalized_payload"], shared[match["sha256"]])
                outcome.update({"status": result["status"], "record_id": str(item["record_id"]),
                                "checks": result["checks"]})
                if args.apply:
                    with connection.transaction():
                        connection.execute(
                            "SELECT set_config('smartlib.actor_id', %s, true)",
                            (str(actor_id),),
                        )
                        apply_record(connection, actor_id, item, match, result)
                    outcome["applied"] = True
            except Exception as exc:
                connection.rollback()
                outcome.update({"status": "failed", "error": str(exc)})
            outcomes.append(outcome)
            print(
                f"[{len(outcomes)}/{len(matches)}] row "
                f"{match['source_row_number']}: {outcome['status']}",
                flush=True,
            )
    counts: dict[str, int] = defaultdict(int)
    for outcome in outcomes:
        counts[outcome["status"]] += 1
    report = {"schema_version": RULE_VERSION, "generated_at": datetime.now(UTC).isoformat(),
              "applied": args.apply, "counts": counts, "records": outcomes}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"counts": counts, "report": str(args.report)}, ensure_ascii=False))
    if counts["failed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
