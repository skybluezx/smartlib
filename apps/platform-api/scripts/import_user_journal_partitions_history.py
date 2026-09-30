#!/usr/bin/env python3
"""Stage every historical sheet in the user-provided journal metrics workbook.

Each worksheet becomes one JCR release. Worksheets that actually contain a
CAS partition column also become a separate CAS partition release. Source rows
are retained even when a title repeats or a quartile contains a compound value.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

from import_user_journal_partitions_2024 import (
    PACKAGE_NAMESPACE,
    apply,
    cas_partition,
    metric_number,
    normalize_text,
    read_xlsx_rows,
    row_checksum,
    validate_package,
)

SHEET_SPECS: dict[str, dict[str, Any]] = {
    "2015": {"headers": ["J_NAME", "IF", "分区"], "rows": 11346},
    "2016": {"headers": ["J_name", "IF", "分区"], "rows": 11487},
    "2017": {"headers": ["J_name", "IF", "分区"], "rows": 11892},
    "2018": {"headers": ["J_name", "IF", "Q分区"], "rows": 11896},
    "2019": {"headers": ["J_name", "IF", "分区"], "rows": 12176},
    "2020": {
        "headers": ["J_name", "IF", "分区", "中科院分区"],
        "rows": 12360,
        "cas_rows": 2068,
    },
    "2021": {
        "headers": ["J_NAME", "IF", "分区", "中科院分区"],
        "rows": 12502,
        "cas_rows": 2081,
    },
    "2022": {
        "headers": ["J_NAME", "IF", "分区", "中科院分区"],
        "rows": 13711,
        "cas_rows": 2054,
    },
    "2023": {
        "headers": ["J9", "J_NAME", "IF", "分区", "中科院分区"],
        "rows": 13602,
        "cas_rows": 2262,
        "title_index": 1,
        "if_index": 2,
        "quartile_index": 3,
        "cas_index": 4,
    },
}


def jcr_quartile(value: object) -> tuple[str | None, str]:
    text = normalize_text(value).upper()
    if text in {"", "N/A", "#N/A", "NONE"}:
        return None, "not_available"
    tokens = [token.strip() for token in text.split(";") if token.strip()]
    quartiles = list(dict.fromkeys(token for token in tokens if token in {"Q1", "Q2", "Q3", "Q4"}))
    unexpected = [token for token in tokens if token not in {"Q1", "Q2", "Q3", "Q4", "N/A", "#N/A", "NONE"}]
    if unexpected or len(quartiles) != 1:
        raise ValueError(f"invalid or ambiguous JCR quartile: {value}")
    return quartiles[0], "compound_value_resolved" if len(tokens) > 1 else "direct"


def build_package(
    workbook: Path,
    source_xls: Path,
    source_xls_sha256: str,
    source_sheet: str,
) -> dict[str, Any]:
    spec = SHEET_SPECS[source_sheet]
    headers = spec["headers"]
    rows = read_xlsx_rows(workbook, source_sheet, len(headers))
    actual_headers = [normalize_text(value) for value in rows[0]] if rows else []
    if actual_headers != headers:
        raise ValueError(f"{source_sheet} worksheet headers do not match: {actual_headers}")

    title_index = spec.get("title_index", 0)
    if_index = spec.get("if_index", 1)
    quartile_index = spec.get("quartile_index", 2)
    cas_index = spec.get("cas_index", 3 if len(headers) > 3 else None)
    dataset_version = f"user-journal-partition-{source_sheet}-{source_xls_sha256[:12].lower()}"
    jcr_records: list[dict[str, Any]] = []
    cas_records: list[dict[str, Any]] = []
    title_counts: Counter[str] = Counter()
    compound_quartile_rows: list[int] = []

    for source_row_number, values in enumerate(rows[1:], start=2):
        if not any(normalize_text(value) for value in values):
            continue
        title = normalize_text(values[title_index])
        if not title:
            raise ValueError(f"{source_sheet} row {source_row_number}: journal title is required")
        normalized_title = title.casefold()
        title_counts[normalized_title] += 1
        impact_factor, upper_bound = metric_number(values[if_index])
        quartile, quartile_parse_status = jcr_quartile(values[quartile_index])
        if quartile_parse_status == "compound_value_resolved":
            compound_quartile_rows.append(source_row_number)
        raw_payload = dict(zip(headers, values, strict=True))
        raw_payload["_jcr_quartile_parse_status"] = quartile_parse_status
        common = {
            "source_row_number": source_row_number,
            "journal": {
                "canonical_title": title,
                "normalized_title": normalized_title,
                "issn": None,
                "eissn": None,
            },
            "record_granularity": "journal",
            "total_citations": None,
            "impact_factor": impact_factor,
            "impact_factor_is_upper_bound": upper_bound,
            "previous_quartile": None,
            "rank_position": None,
            "rank_total": None,
            "raw_payload": raw_payload,
            "row_checksum": row_checksum(raw_payload),
        }
        jcr_records.append(
            {
                **common,
                "record_id": str(uuid5(PACKAGE_NAMESPACE, f"{dataset_version}:jcr:row:{source_row_number}")),
                "quartile": quartile,
                "categories": [],
            }
        )
        if cas_index is not None:
            cas_raw = normalize_text(values[cas_index])
            if cas_raw:
                cas_quartile, categories = cas_partition(cas_raw)
                cas_records.append(
                    {
                        **common,
                        "record_id": str(
                            uuid5(
                                PACKAGE_NAMESPACE,
                                f"{dataset_version}:cas:row:{source_row_number}",
                            )
                        ),
                        "quartile": cas_quartile,
                        "categories": categories,
                    }
                )

    if len(jcr_records) != spec["rows"]:
        raise ValueError(f"{source_sheet}: expected {spec['rows']} JCR rows, found {len(jcr_records)}")
    if len(cas_records) != spec.get("cas_rows", 0):
        raise ValueError(
            f"{source_sheet}: expected {spec.get('cas_rows', 0)} CAS rows, found {len(cas_records)}"
        )

    duplicate_groups = sum(1 for count in title_counts.values() if count > 1)
    duplicate_rows = sum(count for count in title_counts.values() if count > 1)
    releases: dict[str, Any] = {
        "jcr": {
            "metric_system": "jcr",
            "edition_year": int(source_sheet) + 1,
            "metric_year": int(source_sheet),
            "release_label": f"{source_sheet} JIF/JCR Q分区用户提供汇编",
            "publisher_name": "Clarivate口径(文件来源待核)",
            "records": jcr_records,
        }
    }
    if cas_records:
        releases["cas_partition"] = {
            "metric_system": "cas_partition",
            "edition_year": int(source_sheet),
            "metric_year": int(source_sheet),
            "release_label": f"{source_sheet}中科院分区用户提供汇编",
            "publisher_name": "中科院分区口径(文件来源待核)",
            "records": cas_records,
        }

    return {
        "manifest": {
            "dataset_version": dataset_version,
            "source_file": str(source_xls),
            "source_file_sha256": source_xls_sha256.lower(),
            "converted_workbook": str(workbook),
            "converted_workbook_sha256": hashlib.sha256(workbook.read_bytes()).hexdigest(),
            "source_sheet": source_sheet,
            "source_headers": headers,
            "source_kind": "user_provided_compiled_workbook",
            "source_authority_status": "unverified",
            "license_authorization_state": "pending",
            "release_state": "staged",
            "jcr_edition_year": int(source_sheet) + 1,
            "jcr_metric_year": int(source_sheet),
            "cas_edition_year": int(source_sheet) if cas_records else None,
            "cas_metric_year": int(source_sheet) if cas_records else None,
            "jcr_record_count": len(jcr_records),
            "cas_record_count": len(cas_records),
            "jcr_quartile_counts": dict(Counter(record["quartile"] or "N/A" for record in jcr_records)),
            "cas_partition_counts": dict(
                Counter(normalize_text(record["raw_payload"]["中科院分区"]) for record in cas_records)
            ),
            "duplicate_title_group_count": duplicate_groups,
            "duplicate_title_source_row_count": duplicate_rows,
            "compound_jcr_quartile_source_rows": compound_quartile_rows,
            "interpretation": (
                f"The {source_sheet} sheet is a journal-level compilation without ISSN or JCR categories. "
                "JCR and CAS values are stored as separate governed releases. Repeated source rows and "
                "compound source quartiles are retained and documented in raw_payload."
            ),
        },
        "releases": releases,
    }


def preview(packages: list[dict[str, Any]]) -> dict[str, Any]:
    for package in packages:
        validate_package(package)
    return {
        "status": "validated",
        "database_write_state": "preview_only_not_applied",
        "source_authority_status": "unverified",
        "license_authorization_state": "pending",
        "sheets": [
            {
                "source_sheet": package["manifest"]["source_sheet"],
                "jcr_record_count": package["manifest"]["jcr_record_count"],
                "cas_record_count": package["manifest"]["cas_record_count"],
                "jcr_quartile_counts": package["manifest"]["jcr_quartile_counts"],
                "duplicate_title_group_count": package["manifest"]["duplicate_title_group_count"],
                "duplicate_title_source_row_count": package["manifest"]["duplicate_title_source_row_count"],
                "compound_jcr_quartile_source_rows": package["manifest"]["compound_jcr_quartile_source_rows"],
            }
            for package in packages
        ],
        "total_jcr_records": sum(p["manifest"]["jcr_record_count"] for p in packages),
        "total_cas_records": sum(p["manifest"]["cas_record_count"] for p in packages),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Stage historical journal partitions")
    parser.add_argument("--workbook", type=Path, required=True)
    parser.add_argument("--source-xls", type=Path, required=True)
    parser.add_argument("--source-xls-sha256", required=True)
    parser.add_argument("--sheets", default=",".join(SHEET_SPECS))
    parser.add_argument("--report", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    source_checksum = (
        hashlib.sha256(args.source_xls.read_bytes()).hexdigest()
        if args.source_xls.exists()
        else None
    )
    if source_checksum != args.source_xls_sha256.lower():
        raise ValueError("source XLS checksum mismatch")
    requested = [item.strip() for item in args.sheets.split(",") if item.strip()]
    unsupported = sorted(set(requested) - set(SHEET_SPECS))
    if unsupported:
        raise ValueError(f"unsupported sheets: {unsupported}")
    packages = [
        build_package(args.workbook, args.source_xls, args.source_xls_sha256, sheet)
        for sheet in requested
    ]

    if args.apply:
        actor_id = UUID(os.environ.get("SMARTLIB_DEV_ACTOR_ID", "00000000-0000-4000-8000-000000000001"))
        results = [apply(package, os.environ["SMARTLIB_DATABASE_URL"], actor_id) for package in packages]
        result = {
            "status": "staged",
            "database_write_state": "applied",
            "source_authority_status": "unverified",
            "license_authorization_state": "pending",
            "sheets": results,
            "inserted_journal_identities": sum(item["inserted_journal_identities"] for item in results),
            "inserted_releases": sum(item["inserted_releases"] for item in results),
            "inserted_records": sum(item["inserted_records"] for item in results),
            "inserted_categories": sum(item["inserted_categories"] for item in results),
            "audit_event_state": "deferred_admin_insert",
        }
    else:
        result = preview(packages)

    output = json.dumps(result, ensure_ascii=False, indent=2)
    if args.report:
        args.report.write_text(output + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
