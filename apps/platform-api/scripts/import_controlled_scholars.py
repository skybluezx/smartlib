import argparse
import json
import os
from pathlib import Path
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


def load_package(path: Path) -> dict[str, object]:
    package = json.loads(path.read_text(encoding="utf-8"))
    manifest = package["manifest"]
    scholars = package["scholars"]
    if manifest["synthetic"] is not False:
        raise ValueError("controlled scholar import must not be synthetic")
    if manifest["unique_scholars"] != len(scholars):
        raise ValueError("manifest scholar count does not match records")
    if sum(item["publication_row_count"] for item in scholars) != manifest["source_publication_rows"]:
        raise ValueError("source publication row count does not reconcile")
    if len({item["canonical_name"] for item in scholars}) != len(scholars):
        raise ValueError("duplicate canonical names require explicit identity resolution")
    for key in ("object_id", "source_reference_id", "evidence_id", "outbox_event_id", "audit_event_id"):
        values = [UUID(item[key]) for item in scholars]
        if len(set(values)) != len(values):
            raise ValueError(f"duplicate stable identifiers in {key}")
    return package


def import_package(package: dict[str, object], database_url: str, actor_id: UUID) -> dict[str, int]:
    manifest = package["manifest"]
    scholars = package["scholars"]
    dataset_version = manifest["dataset_version"]
    source_system_id = UUID(manifest["source_system_id"])
    license_tags = manifest["license_tags"]

    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        with connection.transaction():
            connection.execute("SELECT set_config('smartlib.actor_id', %s, true)", (str(actor_id),))
            connection.execute(
                """INSERT INTO smartlib.source_system
                          (source_system_id, code, name, owner_department, source_type,
                           authorization_state, metadata)
                     VALUES (%s, %s, %s, %s, %s, %s, %s)
                     ON CONFLICT (code) DO NOTHING""",
                (
                    source_system_id,
                    manifest["source_code"],
                    manifest["source_name"],
                    manifest["source_owner_department"],
                    manifest["source_type"],
                    manifest["source_authorization_state"],
                    Jsonb(
                        {
                            "dataset_id": manifest["dataset_id"],
                            "dataset_version": dataset_version,
                            "synthetic": False,
                            "source_file": manifest["source_file"],
                            "source_file_sha256": manifest["source_file_sha256"],
                            "authorization_note": "用户授权本地受控导入; 正式数据责任部门与展示许可仍待确认",
                        }
                    ),
                ),
            )
            source = connection.execute(
                """SELECT source_system_id, metadata
                     FROM smartlib.source_system WHERE code = %s""",
                (manifest["source_code"],),
            ).fetchone()
            if source is None or source["source_system_id"] != source_system_id:
                raise ValueError("source code is already bound to a different source identity")
            if source["metadata"].get("dataset_version") != dataset_version:
                raise ValueError("source code is already bound to a different dataset version")

            names = [item["canonical_name"] for item in scholars]
            existing_people = connection.execute(
                """SELECT object_id, canonical_name, attributes
                     FROM smartlib.knowledge_object
                    WHERE object_type = 'person'
                      AND system_to = 'infinity'::timestamptz
                      AND canonical_name = ANY(%s)""",
                (names,),
            ).fetchall()
            expected_ids = {item["canonical_name"]: UUID(item["object_id"]) for item in scholars}
            conflicts = [
                row["canonical_name"]
                for row in existing_people
                if row["object_id"] != expected_ids[row["canonical_name"]]
            ]
            if conflicts:
                raise ValueError(
                    "existing same-name people require manual identity reconciliation: "
                    + ", ".join(sorted(conflicts))
                )

            inserted_objects = 0
            for scholar in scholars:
                object_id = UUID(scholar["object_id"])
                description = (
                    "2026年学校国自然代表性论著材料中的获批人; "
                    "当前仅完成姓名级来源登记, 院系、职称、统一人员标识及身份合并待核验。"
                )
                attributes = {
                    "scholar_id": scholar["scholar_id"],
                    "synthetic": False,
                    "dataset_id": manifest["dataset_id"],
                    "dataset_version": dataset_version,
                    "source_role": "获批人",
                    "identity_resolution_status": manifest["identity_resolution"],
                    "source_authorization_state": manifest["source_authorization_state"],
                    "source_order": scholar["source_order"],
                    "publication_row_count": scholar["publication_row_count"],
                    "source_sheet": manifest["sheet"],
                    "source_name_column": manifest["name_column"],
                    "source_excel_rows": scholar["source_excel_rows"],
                }
                object_inserted = connection.execute(
                    """INSERT INTO smartlib.knowledge_object
                              (object_id, object_type, canonical_name, description, visibility,
                               quality_state, review_state, attributes, created_by)
                         VALUES (%s, 'person', %s, %s, %s, %s, %s, %s, %s)
                         ON CONFLICT (object_id) DO NOTHING""",
                    (
                        object_id,
                        scholar["canonical_name"],
                        description,
                        manifest["visibility"],
                        manifest["quality_state"],
                        manifest["review_state"],
                        Jsonb(attributes),
                        actor_id,
                    ),
                ).rowcount
                inserted_objects += object_inserted

                current = connection.execute(
                    """SELECT canonical_name, created_by, attributes
                         FROM smartlib.knowledge_object WHERE object_id = %s""",
                    (object_id,),
                ).fetchone()
                if (
                    current is None
                    or current["canonical_name"] != scholar["canonical_name"]
                    or current["created_by"] != actor_id
                    or current["attributes"].get("dataset_version") != dataset_version
                ):
                    raise ValueError(f"object identity mismatch for {scholar['canonical_name']}")

                row_list = ",".join(str(row) for row in scholar["source_excel_rows"])
                raw_uri = (
                    f"{manifest['source_file']}#sheet={manifest['sheet']}"
                    f"&column={manifest['name_column']}&rows={row_list}"
                )
                reference_metadata = {
                    "dataset_version": dataset_version,
                    "synthetic": False,
                    "sheet": manifest["sheet"],
                    "column": manifest["name_column"],
                    "header": manifest["name_header"],
                    "excel_rows": scholar["source_excel_rows"],
                    "publication_row_count": scholar["publication_row_count"],
                    "identity_resolution_status": manifest["identity_resolution"],
                }
                evidence_excerpt = (
                    f"获批人: {scholar['canonical_name']}; "
                    f"对应代表性论著记录{scholar['publication_row_count']}条。"
                )
                connection.execute(
                    """INSERT INTO smartlib.source_reference
                              (source_reference_id, object_id, source_system_id, external_id,
                               source_version, observed_at, payload_checksum, raw_object_uri,
                               metadata, version)
                         VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 1)
                         ON CONFLICT (source_reference_id) DO NOTHING""",
                    (
                        UUID(scholar["source_reference_id"]),
                        object_id,
                        source_system_id,
                        scholar["external_id"],
                        dataset_version,
                        manifest["source_file_modified_at"],
                        manifest["source_file_sha256"],
                        raw_uri,
                        Jsonb(reference_metadata),
                    ),
                )
                connection.execute(
                    """INSERT INTO smartlib.evidence_record
                              (evidence_id, object_id, source_reference_id, evidence_type,
                               citation, excerpt, visibility, license_tags, content_checksum,
                               metadata, created_by)
                         VALUES (%s, %s, %s, 'business_record', %s, %s, %s, %s, %s, %s, %s)
                         ON CONFLICT (evidence_id) DO NOTHING""",
                    (
                        UUID(scholar["evidence_id"]),
                        object_id,
                        UUID(scholar["source_reference_id"]),
                        f"{manifest['source_name']} / {manifest['sheet']} / B列“获批人” / Excel行{row_list}",
                        evidence_excerpt,
                        manifest["visibility"],
                        license_tags,
                        scholar["content_checksum"],
                        Jsonb(reference_metadata),
                        actor_id,
                    ),
                )
                connection.execute(
                    """INSERT INTO smartlib.outbox_event
                              (event_id, aggregate_type, aggregate_id, event_type,
                               event_version, payload, trace_id)
                         VALUES (%s, 'knowledge_object', %s, 'knowledge.object.imported', 1, %s, %s)
                         ON CONFLICT (event_id) DO NOTHING""",
                    (
                        UUID(scholar["outbox_event_id"]),
                        object_id,
                        Jsonb(
                            {
                                "object_id": str(object_id),
                                "version": 1,
                                "synthetic": False,
                                "dataset_version": dataset_version,
                                "source_external_id": scholar["external_id"],
                            }
                        ),
                        dataset_version,
                    ),
                )
                if object_inserted:
                    connection.execute(
                        """INSERT INTO audit.audit_event
                                  (event_id, actor_id, action, resource_type, resource_id,
                                   decision, trace_id, details)
                             VALUES (%s, %s, 'controlled_file.scholar_imported',
                                     'knowledge_object', %s, 'recorded', %s, %s)""",
                        (
                            UUID(scholar["audit_event_id"]),
                            actor_id,
                            str(object_id),
                            dataset_version,
                            Jsonb(
                                {
                                    "canonical_name": scholar["canonical_name"],
                                    "dataset_version": dataset_version,
                                    "source_external_id": scholar["external_id"],
                                    "identity_resolution_status": manifest["identity_resolution"],
                                }
                            ),
                        ),
                    )

            counts = connection.execute(
                """SELECT
                       count(*) FILTER (WHERE object_type = 'person'
                         AND attributes ->> 'dataset_version' = %s) AS objects,
                       (SELECT count(*) FROM smartlib.source_reference
                         WHERE source_version = %s) AS source_references,
                       (SELECT count(*) FROM smartlib.evidence_record
                         WHERE metadata ->> 'dataset_version' = %s) AS evidence_records,
                       (SELECT count(*) FROM smartlib.outbox_event
                         WHERE trace_id = %s AND aggregate_type = 'knowledge_object') AS outbox_events
                     FROM smartlib.knowledge_object""",
                (dataset_version, dataset_version, dataset_version, dataset_version),
            ).fetchone()
            expected = manifest["unique_scholars"]
            if counts is None or any(counts[key] != expected for key in counts):
                raise ValueError(f"import reconciliation failed: {counts}")
            return {"inserted_objects": inserted_objects, **counts}


def main() -> None:
    parser = argparse.ArgumentParser(description="Import controlled scholar names into SmartLib")
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    package = load_package(args.package)
    manifest = package["manifest"]
    if not args.apply:
        print(
            json.dumps(
                {
                    "status": "validated",
                    "dataset_version": manifest["dataset_version"],
                    "scholars": manifest["unique_scholars"],
                    "publication_rows": manifest["source_publication_rows"],
                    "authorization_state": manifest["source_authorization_state"],
                },
                ensure_ascii=False,
            )
        )
        return
    database_url = os.environ["SMARTLIB_DATABASE_URL"]
    actor_id = UUID(os.environ["SMARTLIB_DEV_ACTOR_ID"])
    result = import_package(package, database_url, actor_id)
    print(json.dumps({"status": "applied", **result}, ensure_ascii=False))


if __name__ == "__main__":
    main()
