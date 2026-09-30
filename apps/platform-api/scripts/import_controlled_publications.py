import argparse
import json
import os
from pathlib import Path
from uuid import UUID, uuid5

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


def load_package(path: Path) -> dict[str, object]:
    package = json.loads(path.read_text(encoding="utf-8"))
    manifest = package["manifest"]
    items = package["items"]
    if manifest["synthetic"] is not False:
        raise ValueError("controlled publication import must not be synthetic")
    if manifest["expected_item_count"] != len(items):
        raise ValueError("manifest publication count does not match records")
    if [item["source_serial"] for item in items] != list(range(1, len(items) + 1)):
        raise ValueError("publication source serials are not contiguous")
    for item in items:
        UUID(item["record_id"])
        UUID(item["awardee_person_id"])
        if len(item["row_checksum"]) != 64:
            raise ValueError("invalid publication row checksum")
    if len({item["record_id"] for item in items}) != len(items):
        raise ValueError("duplicate publication import item identifiers")
    return package


def import_package(package: dict[str, object], database_url: str, actor_id: UUID) -> dict[str, int | str]:
    manifest = package["manifest"]
    items = package["items"]
    dataset_version = manifest["dataset_version"]
    namespace = UUID(manifest["uuid_namespace"])
    batch_id = uuid5(namespace, f"{dataset_version}:batch")
    audit_event_id = uuid5(namespace, f"{dataset_version}:audit:started")

    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        with connection.transaction():
            connection.execute("SELECT set_config('smartlib.actor_id', %s, true)", (str(actor_id),))
            source = connection.execute(
                "SELECT source_system_id FROM smartlib.source_system WHERE source_system_id = %s",
                (UUID(manifest["source_system_id"]),),
            ).fetchone()
            if source is None:
                raise ValueError("controlled publication source system is missing")

            scholar_ids = [UUID(item["awardee_person_id"]) for item in items]
            scholar_count = connection.execute(
                """SELECT count(DISTINCT object_id) AS count
                     FROM smartlib.knowledge_object
                    WHERE object_id = ANY(%s) AND object_type = 'person'
                      AND system_to = 'infinity'::timestamptz""",
                (scholar_ids,),
            ).fetchone()["count"]
            if scholar_count != manifest["unique_awardees"]:
                raise ValueError("controlled awardee identities do not reconcile in PostgreSQL")

            connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (dataset_version,))
            inserted_batch = connection.execute(
                """INSERT INTO smartlib.ingestion_batch
                   (batch_id,source_system_id,dataset_version,source_uri,source_checksum,
                    source_locator,expected_item_count,batch_state,processing_rule_version,
                    metadata,created_by,pipeline_key,source_kind)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'publication','file')
                   ON CONFLICT(dataset_version) DO NOTHING""",
                (batch_id,UUID(manifest["source_system_id"]),dataset_version,manifest["source_file"],
                 manifest["source_file_sha256"],Jsonb({"sheet":manifest["sheet"]}),
                 manifest["expected_item_count"],manifest["batch_state"],
                 "publication-intake-normalization-v1",Jsonb({"synthetic":False,"manifest":manifest}),actor_id),
            ).rowcount
            batch = connection.execute(
                """SELECT batch_id, source_checksum, expected_item_count, created_by
                     FROM smartlib.ingestion_batch WHERE dataset_version = %s""",
                (dataset_version,),
            ).fetchone()
            if (
                batch is None
                or batch["batch_id"] != batch_id
                or batch["source_checksum"] != manifest["source_file_sha256"]
                or batch["expected_item_count"] != manifest["expected_item_count"]
                or batch["created_by"] != actor_id
            ):
                raise ValueError("existing publication batch does not match the controlled package")

            inserted_items = 0
            for item in items:
                inserted = connection.execute(
                    """INSERT INTO smartlib.ingestion_record
                       (record_id,batch_id,source_record_key,source_locator,record_kind,raw_payload,
                        normalized_payload,payload_checksum,processing_state,created_by)
                       VALUES (%s,%s,%s,%s,'publication',%s,%s,%s,'processed',%s)
                       ON CONFLICT(batch_id,source_record_key) DO NOTHING""",
                    (UUID(item["record_id"]),batch_id,
                     json.dumps([manifest["sheet"],item["source_excel_row"]],ensure_ascii=False),
                     Jsonb({"sheet":manifest["sheet"],"row":item["source_excel_row"]}),
                     Jsonb(item["raw_payload"]),Jsonb(item["normalized_payload"]),item["row_checksum"],actor_id),
                ).rowcount
                inserted_items += inserted
                if inserted:
                    connection.execute(
                        """INSERT INTO smartlib.publication_intake_record(record_id,verification_state)
                           VALUES (%s,%s)""",(UUID(item["record_id"]),manifest["initial_verification_state"]),
                    )
                    connection.execute(
                        """INSERT INTO smartlib.representative_work_submission
                           (record_id,representative_work_number,awardee_name_raw,awardee_person_id)
                           VALUES (%s,%s,%s,%s)""",
                        (UUID(item["record_id"]),item["external_id"],item["awardee_name_raw"],
                         UUID(item["awardee_person_id"])),
                    )

            mismatches = connection.execute(
                """SELECT count(*) AS count
                     FROM (smartlib.publication_intake_record item
                  JOIN smartlib.ingestion_record input_record USING(record_id)
                  LEFT JOIN smartlib.representative_work_submission submission USING(record_id))
                    WHERE input_record.batch_id = %s
                      AND NOT EXISTS (
                          SELECT 1 FROM jsonb_to_recordset(%s::jsonb)
                              AS package_item(record_id uuid, row_checksum text)
                           WHERE package_item.record_id = item.record_id
                             AND package_item.row_checksum = input_record.payload_checksum
                      )""",
                (
                    batch_id,
                    Jsonb(
                        [
                            {
                                "record_id": item["record_id"],
                                "row_checksum": item["row_checksum"],
                            }
                            for item in items
                        ]
                    ),
                ),
            ).fetchone()["count"]
            total_items = connection.execute(
                """SELECT count(*) AS count FROM smartlib.ingestion_record input_record
                   WHERE input_record.batch_id = %s""",
                (batch_id,),
            ).fetchone()["count"]
            if total_items != manifest["expected_item_count"] or mismatches:
                raise ValueError(
                    f"publication intake reconciliation failed: total={total_items}, mismatches={mismatches}"
                )

            if inserted_batch:
                connection.execute(
                    """INSERT INTO audit.audit_event
                              (event_id, actor_id, action, resource_type, resource_id,
                               decision, trace_id, details)
                         VALUES (%s, %s, 'controlled_file.publication_intake_started',
                                 'ingestion_batch', %s, 'recorded', %s, %s)""",
                    (
                        audit_event_id,
                        actor_id,
                        str(batch_id),
                        dataset_version,
                        Jsonb(
                            {
                                "dataset_version": dataset_version,
                                "item_count": total_items,
                                "synthetic": False,
                            }
                        ),
                    ),
                )
            return {
                "status": "verifying",
                "batch_id": str(batch_id),
                "inserted_batch": inserted_batch,
                "inserted_items": inserted_items,
                "total_items": total_items,
            }


def main() -> None:
    parser = argparse.ArgumentParser(description="Import controlled publication intake records")
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    package = load_package(args.package)
    if not args.apply:
        print(json.dumps({"status": "validated", **package["manifest"]}, ensure_ascii=False))
        return
    result = import_package(
        package, os.environ["SMARTLIB_DATABASE_URL"], UUID(os.environ["SMARTLIB_DEV_ACTOR_ID"])
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
