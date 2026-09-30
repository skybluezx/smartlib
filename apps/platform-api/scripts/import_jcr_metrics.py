import argparse
import json
import os
from pathlib import Path
from uuid import UUID, uuid5

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from smartlib_platform.journal_metrics.workbook import PACKAGE_NAMESPACE, build_package


def validate_package(package: dict[str, object]) -> dict[str, object]:
    manifest = package["manifest"]
    records = package["records"]
    if manifest["metric_system"] != "jcr":
        raise ValueError("this importer only accepts JCR metric packages")
    if manifest["source_authority_status"] != "unverified":
        raise ValueError("workbook intake must begin with unverified source authority")
    if manifest["license_authorization_state"] != "pending":
        raise ValueError("workbook intake must begin with pending license review")
    if manifest["release_state"] != "staged":
        raise ValueError("workbook intake must begin in staged state")
    if manifest["expected_record_count"] != len(records):
        raise ValueError("manifest record count does not match JCR records")
    source_rows = [record["source_row_number"] for record in records]
    if len(source_rows) != len(set(source_rows)):
        raise ValueError("duplicate source row numbers in JCR package")
    if any(len(record["row_checksum"]) != 64 for record in records):
        raise ValueError("invalid JCR row checksum")
    return package


def _journal_key(journal: dict[str, object]) -> str:
    return str(journal["issn"] or journal["eissn"] or journal["normalized_title"])


def import_package(
    package: dict[str, object], database_url: str, actor_id: UUID
) -> dict[str, int | str]:
    package = validate_package(package)
    manifest = package["manifest"]
    records = package["records"]
    dataset_version = str(manifest["dataset_version"])
    checksum = str(manifest["source_file_sha256"])
    edition_year = int(manifest["edition_year"])
    source_system_id = uuid5(PACKAGE_NAMESPACE, "jcr:source:local-workbook-intake")
    domain_id = uuid5(PACKAGE_NAMESPACE, "governance-domain:publication-metrics")
    asset_id = uuid5(PACKAGE_NAMESPACE, f"{dataset_version}:asset")
    asset_version_id = uuid5(PACKAGE_NAMESPACE, f"{dataset_version}:asset-version:1")
    license_id = uuid5(PACKAGE_NAMESPACE, f"{dataset_version}:license-review")
    release_id = uuid5(PACKAGE_NAMESPACE, f"{dataset_version}:release")
    audit_event_id = uuid5(PACKAGE_NAMESPACE, f"{dataset_version}:audit:staged")

    inserted_records = 0
    inserted_categories = 0
    journal_cache: dict[str, UUID] = {}
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        with connection.transaction():
            connection.execute("SELECT set_config('smartlib.actor_id', %s, true)", (str(actor_id),))
            connection.execute(
                """INSERT INTO smartlib.source_system
                          (source_system_id, code, name, owner_department, source_type,
                           authorization_state, metadata)
                     VALUES (%s, 'jcr_workbook_intake', 'JCR workbook intake',
                             '图书馆数据治理', 'licensed_resource', 'pending', %s)
                     ON CONFLICT (source_system_id) DO NOTHING""",
                (
                    source_system_id,
                    Jsonb(
                        {
                            "authority_warning": "Local workbook provenance is not yet verified",
                            "publisher_claim": manifest["publisher_name"],
                        }
                    ),
                ),
            )
            connection.execute(
                """INSERT INTO smartlib.governance_domain
                          (governance_domain_id, code, name, description, visibility, created_by)
                     VALUES (%s, 'publication_metrics', '论文指标数据',
                             '论文治理使用的期刊级、年度化、来源受控指标', 'restricted', %s)
                     ON CONFLICT (governance_domain_id) DO NOTHING""",
                (domain_id, actor_id),
            )
            connection.execute(
                """INSERT INTO smartlib.data_asset
                          (data_asset_id, governance_domain_id, source_system_id, code, name,
                           description, asset_type, lifecycle_state, visibility, synthetic,
                           metadata, created_by)
                     VALUES (%s, %s, %s, %s, %s,
                             'JCR journal metrics; not a person-level evaluation score',
                             'licensed_resource', 'draft', 'restricted', false, %s, %s)
                     ON CONFLICT (data_asset_id) DO NOTHING""",
                (
                    asset_id,
                    domain_id,
                    source_system_id,
                    f"jcr_{edition_year}_{checksum[:12]}",
                    f"JCR {edition_year} 期刊指标暂存版本",
                    Jsonb(
                        {
                            "dataset_version": dataset_version,
                            "authority_status": "unverified",
                            "license_status": "pending",
                            "metric_scope": "journal",
                        }
                    ),
                    actor_id,
                ),
            )
            connection.execute(
                """INSERT INTO smartlib.data_asset_version
                          (data_asset_version_id, data_asset_id, version_number, schema_version,
                           checksum, metadata, created_by)
                     VALUES (%s, %s, 1, 'journal-metric-v1', %s, %s, %s)
                     ON CONFLICT (data_asset_version_id) DO NOTHING""",
                (
                    asset_version_id,
                    asset_id,
                    checksum,
                    Jsonb(
                        {
                            "source_file": manifest["source_file"],
                            "source_sheet": manifest["source_sheet"],
                            "expected_record_count": manifest["expected_record_count"],
                        }
                    ),
                    actor_id,
                ),
            )
            connection.execute(
                """INSERT INTO smartlib.license_grant
                          (license_grant_id, data_asset_id, license_name, license_reference,
                           authorization_state, allowed_content, allowed_purposes,
                           prohibited_purposes, terms_metadata, synthetic, created_by)
                     VALUES (%s, %s, 'JCR data license review pending', %s, 'pending',
                             ARRAY[]::text[], ARRAY[]::text[],
                             ARRAY['publication_governance', 'redistribution']::text[], %s,
                             false, %s)
                     ON CONFLICT (license_grant_id) DO NOTHING""",
                (
                    license_id,
                    asset_id,
                    str(manifest["source_file"]),
                    Jsonb({"review_required": True, "publisher_claim": manifest["publisher_name"]}),
                    actor_id,
                ),
            )
            inserted_release = connection.execute(
                """INSERT INTO smartlib.journal_metric_release
                          (release_id, data_asset_version_id, metric_system, edition_year,
                           metric_year, release_label, publisher_name, source_uri, source_sheet,
                           source_file_checksum, expected_record_count, authority_status,
                           release_state, metadata, created_by)
                     VALUES (%s, %s, 'jcr', %s, %s, %s, %s, %s, %s, %s, %s,
                             'unverified', 'staged', %s, %s)
                     ON CONFLICT (release_id) DO NOTHING""",
                (
                    release_id,
                    asset_version_id,
                    edition_year,
                    int(manifest["metric_year"]),
                    manifest["release_label"],
                    manifest["publisher_name"],
                    manifest["source_file"],
                    manifest["source_sheet"],
                    checksum,
                    manifest["expected_record_count"],
                    Jsonb(
                        {
                            "profile": manifest["profile"],
                            "authority_review_required": True,
                            "license_review_required": True,
                        }
                    ),
                    actor_id,
                ),
            ).rowcount

            existing_journals = connection.execute(
                "SELECT journal_id, normalized_title, issn, eissn FROM smartlib.journal_identity"
            ).fetchall()
            identity_by_issn = {
                row["issn"]: row["journal_id"] for row in existing_journals if row["issn"]
            }
            identity_by_eissn = {
                row["eissn"]: row["journal_id"] for row in existing_journals if row["eissn"]
            }
            identity_by_title = {
                row["normalized_title"].casefold(): row["journal_id"] for row in existing_journals
            }
            journal_rows = []
            record_rows = []
            category_rows = []
            for record in records:
                journal = record["journal"]
                key = _journal_key(journal)
                journal_id = journal_cache.get(key)
                if journal_id is None:
                    journal_id = (
                        identity_by_issn.get(journal["issn"])
                        or identity_by_eissn.get(journal["eissn"])
                        or identity_by_title.get(journal["normalized_title"].casefold())
                    )
                    if journal_id is None:
                        journal_id = uuid5(PACKAGE_NAMESPACE, f"journal:{key}")
                        journal_rows.append(
                            (
                                journal_id,
                                journal["canonical_title"],
                                journal["normalized_title"],
                                journal["issn"],
                                journal["eissn"],
                                actor_id,
                            )
                        )
                        if journal["issn"]:
                            identity_by_issn[journal["issn"]] = journal_id
                        if journal["eissn"]:
                            identity_by_eissn[journal["eissn"]] = journal_id
                        identity_by_title[journal["normalized_title"].casefold()] = journal_id
                    journal_cache[key] = journal_id

                record_id = UUID(record["record_id"])
                record_rows.append(
                    (
                        record_id,
                        release_id,
                        journal_id,
                        record["source_row_number"],
                        record["record_granularity"],
                        record["total_citations"],
                        record["impact_factor"],
                        record["impact_factor_is_upper_bound"],
                        record["quartile"],
                        record["previous_quartile"],
                        record["rank_position"],
                        record["rank_total"],
                        Jsonb(record["raw_payload"]),
                        record["row_checksum"],
                        actor_id,
                    )
                )
                for category in record["categories"]:
                    category_id = uuid5(
                        PACKAGE_NAMESPACE,
                        f"{record_id}:category:{category['category_order']}",
                    )
                    category_rows.append(
                        (
                            category_id,
                            record_id,
                            category["category_order"],
                            category["category_name"],
                            category["citation_indexes"],
                            actor_id,
                        )
                    )

            with connection.cursor() as cursor:
                cursor.executemany(
                    """INSERT INTO smartlib.journal_identity
                              (journal_id, canonical_title, normalized_title, issn, eissn, created_by)
                         VALUES (%s, %s, %s, %s, %s, %s)
                         ON CONFLICT (journal_id) DO NOTHING""",
                    journal_rows,
                )
                cursor.executemany(
                    """INSERT INTO smartlib.journal_metric_record
                              (record_id, release_id, journal_id, source_row_number,
                               record_granularity, total_citations, impact_factor,
                               impact_factor_is_upper_bound, quartile, previous_quartile,
                               rank_position, rank_total, raw_payload, row_checksum, created_by)
                         VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                         ON CONFLICT (record_id) DO NOTHING""",
                    record_rows,
                )
                inserted_records = cursor.rowcount
                cursor.executemany(
                    """INSERT INTO smartlib.journal_metric_record_category
                              (record_category_id, record_id, category_order,
                               category_name, citation_indexes, created_by)
                         VALUES (%s, %s, %s, %s, %s, %s)
                         ON CONFLICT (record_category_id) DO NOTHING""",
                    category_rows,
                )
                inserted_categories = cursor.rowcount

            actual = connection.execute(
                """SELECT count(*) AS record_count,
                          count(DISTINCT journal_id) AS journal_count
                     FROM smartlib.journal_metric_record WHERE release_id = %s""",
                (release_id,),
            ).fetchone()
            if actual["record_count"] != manifest["expected_record_count"]:
                raise ValueError(
                    "JCR import reconciliation failed: "
                    f"expected={manifest['expected_record_count']}, actual={actual['record_count']}"
                )
            if inserted_release:
                connection.execute(
                    """INSERT INTO audit.audit_event
                              (event_id, actor_id, action, resource_type, resource_id,
                               decision, trace_id, details)
                         VALUES (%s, %s, 'journal_metric.release_staged',
                                 'journal_metric_release', %s, 'recorded', %s, %s)""",
                    (
                        audit_event_id,
                        actor_id,
                        str(release_id),
                        dataset_version,
                        Jsonb(
                            {
                                "record_count": actual["record_count"],
                                "journal_count": actual["journal_count"],
                                "authority_status": "unverified",
                                "license_status": "pending",
                            }
                        ),
                    ),
                )
    return {
        "status": "staged",
        "release_id": str(release_id),
        "record_count": int(actual["record_count"]),
        "journal_count": int(actual["journal_count"]),
        "inserted_records": inserted_records,
        "inserted_categories": inserted_categories,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Stage a governed JCR workbook release")
    parser.add_argument("--workbook", type=Path, required=True)
    parser.add_argument("--profile", choices=("jcr-2025", "jcr-2026"), required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    package = validate_package(build_package(args.workbook, args.profile))
    if not args.apply:
        print(json.dumps({"status": "validated", **package["manifest"]}, ensure_ascii=False))
        return
    result = import_package(
        package, os.environ["SMARTLIB_DATABASE_URL"], UUID(os.environ["SMARTLIB_DEV_ACTOR_ID"])
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
