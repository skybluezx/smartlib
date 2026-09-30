#!/usr/bin/env python3
"""Stage the user-provided 2024 journal metric workbook as two governed releases.

The workbook's JCR Q quartile and CAS partition columns are stored as separate
metric systems.  Both releases remain unverified/staged until provenance and
license review are completed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from smartlib_platform.journal_metrics.workbook import (
    PACKAGE_NAMESPACE,
    normalize_text,
    parse_quartile,
    read_xlsx_rows,
)
from smartlib_platform.journals.normalization import journal_key, normalized_title

SOURCE_HEADERS = ["J_name", "IF", "Q分区", "中科院分区"]
SOURCE_SHEET = "2024"
SOURCE_CODE = "user_journal_partition_workbook"
SOURCE_SYSTEM_ID = uuid5(PACKAGE_NAMESPACE, "journal-metric:source:user-provided-workbook")
DOMAIN_ID = uuid5(PACKAGE_NAMESPACE, "governance-domain:publication-metrics")


def _unique_identity_index(rows: list[dict[str, Any]]) -> tuple[dict[str, UUID], dict[str, UUID]]:
    """Build exact and punctuation-tolerant indexes without guessing ambiguous titles."""

    exact_groups: dict[str, set[UUID]] = {}
    key_groups: dict[str, set[UUID]] = {}
    for row in rows:
        journal_id = row["journal_id"]
        title = normalized_title(row["normalized_title"])
        exact_groups.setdefault(title, set()).add(journal_id)
        key_groups.setdefault(journal_key(title), set()).add(journal_id)
    exact = {key: next(iter(values)) for key, values in exact_groups.items() if len(values) == 1}
    compact = {
        key: next(iter(values))
        for key, values in key_groups.items()
        if key and len(values) == 1
    }
    return exact, compact


def metric_number(value: object) -> tuple[float | None, bool]:
    text = normalize_text(value)
    if text.upper() in {"", "N/A", "#N/A", "NONE"}:
        return None, False
    upper_bound = text.startswith("<")
    numeric = text[1:].strip() if upper_bound else text
    try:
        parsed = float(numeric)
    except ValueError as error:
        raise ValueError(f"invalid impact factor: {value}") from error
    if parsed < 0:
        raise ValueError(f"negative impact factor: {value}")
    return parsed, upper_bound


def cas_partition(value: object) -> tuple[str | None, list[dict[str, Any]]]:
    text = normalize_text(value)
    if not text:
        return None, []
    if text == "无":
        return None, []
    match = re.fullmatch(r"(.+?)([1-4])区", text)
    if match is None:
        raise ValueError(f"invalid CAS partition: {value}")
    category = normalize_text(match.group(1))
    return f"Q{match.group(2)}", [
        {"category_order": 1, "category_name": category, "citation_indexes": []}
    ]


def row_checksum(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_package(
    workbook: Path, source_xls: Path, source_xls_sha256: str
) -> dict[str, Any]:
    rows = read_xlsx_rows(workbook, SOURCE_SHEET, len(SOURCE_HEADERS))
    actual_headers = [normalize_text(value) for value in rows[0]] if rows else []
    if actual_headers != SOURCE_HEADERS:
        raise ValueError(f"2024 worksheet headers do not match: {actual_headers}")
    if not re.fullmatch(r"[A-Fa-f0-9]{64}", source_xls_sha256):
        raise ValueError("source XLS checksum must be SHA-256")
    actual_source_checksum = hashlib.sha256(source_xls.read_bytes()).hexdigest()
    if actual_source_checksum.lower() != source_xls_sha256.lower():
        raise ValueError("source XLS checksum mismatch")

    converted_checksum = hashlib.sha256(workbook.read_bytes()).hexdigest()
    dataset_version = f"user-journal-partition-2024-{source_xls_sha256[:12].lower()}"
    jcr_records: list[dict[str, Any]] = []
    cas_records: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    for source_row_number, values in enumerate(rows[1:], start=2):
        if not any(normalize_text(value) for value in values):
            continue
        title = normalize_text(values[0])
        if not title:
            raise ValueError(f"row {source_row_number}: journal title is required")
        normalized_title = title.casefold()
        if normalized_title in seen_titles:
            raise ValueError(f"row {source_row_number}: duplicate normalized journal title {title}")
        seen_titles.add(normalized_title)
        impact_factor, upper_bound = metric_number(values[1])
        quartile = parse_quartile(values[2])
        raw_payload = dict(zip(SOURCE_HEADERS, values, strict=True))
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
                "record_id": str(
                    uuid5(PACKAGE_NAMESPACE, f"{dataset_version}:jcr:row:{source_row_number}")
                ),
                "quartile": quartile,
                "categories": [],
            }
        )
        cas_raw = normalize_text(values[3])
        if cas_raw:
            cas_quartile, categories = cas_partition(cas_raw)
            cas_records.append(
                {
                    **common,
                    "record_id": str(
                        uuid5(PACKAGE_NAMESPACE, f"{dataset_version}:cas:row:{source_row_number}")
                    ),
                    "quartile": cas_quartile,
                    "categories": categories,
                }
            )

    if len(jcr_records) != 13539:
        raise ValueError(f"expected 13539 JCR rows, found {len(jcr_records)}")
    if len(cas_records) != 1371:
        raise ValueError(f"expected 1371 nonblank CAS rows, found {len(cas_records)}")

    return {
        "manifest": {
            "dataset_version": dataset_version,
            "source_file": str(source_xls),
            "source_file_sha256": source_xls_sha256.lower(),
            "converted_workbook": str(workbook),
            "converted_workbook_sha256": converted_checksum,
            "source_sheet": SOURCE_SHEET,
            "source_headers": SOURCE_HEADERS,
            "source_kind": "user_provided_compiled_workbook",
            "source_authority_status": "unverified",
            "license_authorization_state": "pending",
            "release_state": "staged",
            "jcr_edition_year": 2025,
            "jcr_metric_year": 2024,
            "cas_edition_year": 2024,
            "cas_metric_year": 2024,
            "jcr_record_count": len(jcr_records),
            "cas_record_count": len(cas_records),
            "jcr_quartile_counts": dict(Counter(record["quartile"] or "N/A" for record in jcr_records)),
            "cas_partition_counts": dict(
                Counter(normalize_text(record["raw_payload"]["中科院分区"]) for record in cas_records)
            ),
            "interpretation": (
                "The 2024 sheet is a journal-level compilation without ISSN or JCR categories. "
                "JCR Q quartile and CAS partition are stored as separate governed releases."
            ),
        },
        "releases": {
            "jcr": {
                "metric_system": "jcr",
                "edition_year": 2025,
                "metric_year": 2024,
                "release_label": "2024 JIF/JCR Q分区用户提供汇编",
                "publisher_name": "Clarivate口径(文件来源待核)",
                "records": jcr_records,
            },
            "cas_partition": {
                "metric_system": "cas_partition",
                "edition_year": 2024,
                "metric_year": 2024,
                "release_label": "2024中科院分区用户提供汇编",
                "publisher_name": "中科院分区口径(文件来源待核)",
                "records": cas_records,
            },
        },
    }


def validate_package(package: dict[str, Any]) -> None:
    manifest = package["manifest"]
    if manifest["source_authority_status"] != "unverified":
        raise ValueError("user workbook must enter as unverified")
    if manifest["license_authorization_state"] != "pending":
        raise ValueError("user workbook license must enter as pending")
    if manifest["release_state"] != "staged":
        raise ValueError("user workbook release must enter as staged")
    for key, release in package["releases"].items():
        records = release["records"]
        expected = manifest[f"{'jcr' if key == 'jcr' else 'cas'}_record_count"]
        if len(records) != expected:
            raise ValueError(f"{key} record count mismatch")
        source_rows = [record["source_row_number"] for record in records]
        if len(source_rows) != len(set(source_rows)):
            raise ValueError(f"{key} duplicate source rows")
        if len({record["record_id"] for record in records}) != len(records):
            raise ValueError(f"{key} duplicate record identifiers")


def plan(package: dict[str, Any]) -> dict[str, Any]:
    validate_package(package)
    manifest = package["manifest"]
    jcr = package["releases"]["jcr"]["records"]
    cas = package["releases"]["cas_partition"]["records"]
    return {
        "status": "validated",
        "dataset_version": manifest["dataset_version"],
        "source_file_sha256": manifest["source_file_sha256"],
        "source_sheet": manifest["source_sheet"],
        "unique_journals": len(jcr),
        "jcr_record_count": len(jcr),
        "cas_record_count": len(cas),
        "cas_category_record_count": sum(len(record["categories"]) for record in cas),
        "jcr_quartile_counts": manifest["jcr_quartile_counts"],
        "source_authority_status": "unverified",
        "license_authorization_state": "pending",
        "release_state": "staged",
        "database_write_state": "preview_only_not_applied",
    }


def release_ids(dataset_version: str, metric_system: str) -> dict[str, UUID]:
    return {
        "asset_id": uuid5(PACKAGE_NAMESPACE, f"{dataset_version}:{metric_system}:asset"),
        "asset_version_id": uuid5(
            PACKAGE_NAMESPACE, f"{dataset_version}:{metric_system}:asset-version:1"
        ),
        "license_id": uuid5(PACKAGE_NAMESPACE, f"{dataset_version}:{metric_system}:license-review"),
        "release_id": uuid5(PACKAGE_NAMESPACE, f"{dataset_version}:{metric_system}:release"),
    }


def apply(package: dict[str, Any], database_url: str, actor_id: UUID) -> dict[str, Any]:
    validate_package(package)
    manifest = package["manifest"]
    dataset_version = manifest["dataset_version"]
    source_sheet = manifest["source_sheet"]
    inserted_journals = inserted_releases = inserted_records = inserted_categories = 0
    release_results: dict[str, Any] = {}

    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        with connection.transaction():
            connection.execute("SELECT set_config('smartlib.actor_id', %s, true)", (str(actor_id),))
            connection.execute(
                """INSERT INTO smartlib.source_system
                          (source_system_id,code,name,owner_department,source_type,
                           authorization_state,metadata)
                     VALUES (%s,%s,'用户提供期刊分区汇编','图书馆数据治理','file','pending',%s)
                     ON CONFLICT (source_system_id) DO NOTHING""",
                (
                    SOURCE_SYSTEM_ID,
                    SOURCE_CODE,
                    Jsonb(
                        {
                            "source_kind": "user_provided_compiled_workbook",
                            "authority_warning": "原始发布机构、版本和授权尚未核验",
                            "synthetic": False,
                        }
                    ),
                ),
            )
            connection.execute(
                """INSERT INTO smartlib.governance_domain
                          (governance_domain_id,code,name,description,visibility,created_by)
                     VALUES (%s,'publication_metrics','论文指标数据',
                             '论文治理使用的期刊级、年度化、来源受控指标','restricted',%s)
                     ON CONFLICT (governance_domain_id) DO NOTHING""",
                (DOMAIN_ID, actor_id),
            )

            existing = connection.execute(
                """SELECT journal_id,normalized_title
                     FROM smartlib.journal_identity
                    UNION ALL
                   SELECT journal_id,normalized_name
                     FROM smartlib.journal_name_variant"""
            ).fetchall()
            identity_by_title, identity_by_key = _unique_identity_index(existing)
            source_identity_by_title: dict[str, UUID] = {}
            journal_rows: list[tuple[Any, ...]] = []
            all_jcr_records = package["releases"]["jcr"]["records"]
            for record in all_jcr_records:
                journal = record["journal"]
                normalized = normalized_title(journal["normalized_title"])
                compact = journal_key(normalized)
                journal_id = identity_by_title.get(normalized) or identity_by_key.get(compact)
                if journal_id is None:
                    journal_id = uuid5(PACKAGE_NAMESPACE, f"journal:{normalized}")
                    identity_by_title[normalized] = journal_id
                    if compact:
                        identity_by_key[compact] = journal_id
                    journal_rows.append(
                        (
                            journal_id,
                            journal["canonical_title"],
                            normalized,
                            actor_id,
                        )
                    )
                source_identity_by_title[normalized] = journal_id
            with connection.cursor() as cursor:
                cursor.executemany(
                    """INSERT INTO smartlib.journal_identity
                              (journal_id,canonical_title,normalized_title,created_by)
                         VALUES (%s,%s,%s,%s)
                         ON CONFLICT (journal_id) DO NOTHING""",
                    journal_rows,
                )
                inserted_journals = max(cursor.rowcount, 0)

            for release_key, release in package["releases"].items():
                metric_system = release["metric_system"]
                ids = release_ids(dataset_version, metric_system)
                checksum = manifest["source_file_sha256"]
                asset_code = f"journal_metric_{metric_system}_{source_sheet}_{checksum[:12]}"
                connection.execute(
                    """INSERT INTO smartlib.data_asset
                              (data_asset_id,governance_domain_id,source_system_id,code,name,
                               description,asset_type,lifecycle_state,visibility,synthetic,
                               metadata,created_by)
                         VALUES (%s,%s,%s,%s,%s,%s,'licensed_resource','draft','restricted',
                                 false,%s,%s)
                         ON CONFLICT (data_asset_id) DO NOTHING""",
                    (
                        ids["asset_id"], DOMAIN_ID, SOURCE_SYSTEM_ID, asset_code,
                        release["release_label"],
                        "用户提供的期刊级分区汇编; 原始来源和使用授权待核验",
                        Jsonb(
                            {
                                "dataset_version": dataset_version,
                                "metric_system": metric_system,
                                "metric_scope": "journal",
                                "authority_status": "unverified",
                                "license_status": "pending",
                                "source_has_issn": False,
                                "source_has_jcr_categories": False,
                            }
                        ),
                        actor_id,
                    ),
                )
                connection.execute(
                    """INSERT INTO smartlib.data_asset_version
                              (data_asset_version_id,data_asset_id,version_number,schema_version,
                               checksum,metadata,created_by)
                         VALUES (%s,%s,1,'journal-metric-v1',%s,%s,%s)
                         ON CONFLICT (data_asset_version_id) DO NOTHING""",
                    (
                        ids["asset_version_id"], ids["asset_id"], checksum,
                        Jsonb(
                            {
                                "source_file": manifest["source_file"],
                                "converted_workbook_sha256": manifest["converted_workbook_sha256"],
                                "source_sheet": source_sheet,
                                "expected_record_count": len(release["records"]),
                            }
                        ),
                        actor_id,
                    ),
                )
                connection.execute(
                    """INSERT INTO smartlib.license_grant
                              (license_grant_id,data_asset_id,license_name,license_reference,
                               authorization_state,allowed_content,allowed_purposes,
                               prohibited_purposes,terms_metadata,synthetic,created_by)
                         VALUES (%s,%s,'用户提供期刊分区文件: 授权审核待完成',%s,'pending',
                                 ARRAY[]::text[],ARRAY[]::text[],
                                 ARRAY['publication_governance','redistribution']::text[],%s,
                                 false,%s)
                         ON CONFLICT (license_grant_id) DO NOTHING""",
                    (
                        ids["license_id"], ids["asset_id"], manifest["source_file"],
                        Jsonb(
                            {
                                "review_required": True,
                                "received_via": "user_attachment",
                                "source_authority_status": "unverified",
                            }
                        ),
                        actor_id,
                    ),
                )
                inserted_releases += connection.execute(
                    """INSERT INTO smartlib.journal_metric_release
                              (release_id,data_asset_version_id,metric_system,edition_year,
                               metric_year,release_label,publisher_name,source_uri,source_sheet,
                               source_file_checksum,expected_record_count,authority_status,
                               release_state,metadata,created_by)
                         VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                                 'unverified','staged',%s,%s)
                         ON CONFLICT (release_id) DO NOTHING""",
                    (
                        ids["release_id"], ids["asset_version_id"], metric_system,
                        release["edition_year"], release["metric_year"], release["release_label"],
                        release["publisher_name"], manifest["source_file"], source_sheet,
                        checksum, len(release["records"]),
                        Jsonb(
                            {
                                "dataset_version": dataset_version,
                                "profile": f"user-compiled-{source_sheet}",
                                "source_headers": manifest["source_headers"],
                                "authority_review_required": True,
                                "license_review_required": True,
                                "converted_workbook_sha256": manifest["converted_workbook_sha256"],
                                "interpretation": manifest["interpretation"],
                            }
                        ),
                        actor_id,
                    ),
                ).rowcount

                record_rows: list[tuple[Any, ...]] = []
                category_rows: list[tuple[Any, ...]] = []
                for record in release["records"]:
                    journal_id = source_identity_by_title[
                        normalized_title(record["journal"]["normalized_title"])
                    ]
                    record_id = UUID(record["record_id"])
                    record_rows.append(
                        (
                            record_id, ids["release_id"], journal_id,
                            record["source_row_number"], record["record_granularity"],
                            record["total_citations"], record["impact_factor"],
                            record["impact_factor_is_upper_bound"], record["quartile"],
                            record["previous_quartile"], record["rank_position"],
                            record["rank_total"], Jsonb(record["raw_payload"]),
                            record["row_checksum"], actor_id,
                        )
                    )
                    for category in record["categories"]:
                        category_rows.append(
                            (
                                uuid5(
                                    PACKAGE_NAMESPACE,
                                    f"{record_id}:category:{category['category_order']}",
                                ),
                                record_id, category["category_order"], category["category_name"],
                                category["citation_indexes"], actor_id,
                            )
                        )
                with connection.cursor() as cursor:
                    cursor.executemany(
                        """INSERT INTO smartlib.journal_metric_record
                                  (record_id,release_id,journal_id,source_row_number,
                                   record_granularity,total_citations,impact_factor,
                                   impact_factor_is_upper_bound,quartile,previous_quartile,
                                   rank_position,rank_total,raw_payload,row_checksum,created_by)
                             VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                             ON CONFLICT (record_id) DO NOTHING""",
                        record_rows,
                    )
                    inserted_records += max(cursor.rowcount, 0)
                    if category_rows:
                        cursor.executemany(
                            """INSERT INTO smartlib.journal_metric_record_category
                                      (record_category_id,record_id,category_order,category_name,
                                       citation_indexes,created_by)
                                 VALUES (%s,%s,%s,%s,%s,%s)
                                 ON CONFLICT (record_category_id) DO NOTHING""",
                            category_rows,
                        )
                        inserted_categories += max(cursor.rowcount, 0)

                actual = connection.execute(
                    """SELECT count(*) AS record_count,count(DISTINCT journal_id) AS journal_count
                         FROM smartlib.journal_metric_record WHERE release_id=%s""",
                    (ids["release_id"],),
                ).fetchone()
                category_count = connection.execute(
                    """SELECT count(*) AS category_count
                         FROM smartlib.journal_metric_record_category category
                         JOIN smartlib.journal_metric_record record
                           ON record.record_id=category.record_id
                        WHERE record.release_id=%s""",
                    (ids["release_id"],),
                ).fetchone()["category_count"]
                if actual["record_count"] != len(release["records"]):
                    raise ValueError(
                        f"{metric_system} import reconciliation failed: "
                        f"{actual['record_count']}/{len(release['records'])}"
                    )
                release_results[release_key] = {
                    "release_id": str(ids["release_id"]),
                    "record_count": int(actual["record_count"]),
                    "journal_count": int(actual["journal_count"]),
                    "category_count": int(category_count),
                    "authority_status": "unverified",
                    "release_state": "staged",
                }

    return {
        "status": "staged",
        "dataset_version": dataset_version,
        "source_file_sha256": manifest["source_file_sha256"],
        "inserted_journal_identities": inserted_journals,
        "inserted_releases": inserted_releases,
        "inserted_records": inserted_records,
        "inserted_categories": inserted_categories,
        "releases": release_results,
        "source_authority_status": "unverified",
        "license_authorization_state": "pending",
        "database_write_state": "applied",
        "audit_event_state": "deferred_admin_insert",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Stage user-provided 2024 journal partitions")
    parser.add_argument("--workbook", type=Path, required=True)
    parser.add_argument("--source-xls", type=Path, required=True)
    parser.add_argument("--source-xls-sha256", required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    package = build_package(args.workbook, args.source_xls, args.source_xls_sha256)
    result = (
        apply(
            package,
            os.environ["SMARTLIB_DATABASE_URL"],
            UUID(os.environ.get("SMARTLIB_DEV_ACTOR_ID", "00000000-0000-4000-8000-000000000001")),
        )
        if args.apply
        else plan(package)
    )
    output = json.dumps(result, ensure_ascii=False, indent=2)
    if args.report:
        args.report.write_text(output + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
