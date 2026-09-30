import argparse
import json
import os
from pathlib import Path
from uuid import UUID, uuid5

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

PROJECT_NAMESPACE = UUID("6b274286-a556-4dc1-a65d-ec6b2e9af908")
ANNUAL_PROGRAM_ID = UUID("ee6e00e3-be0f-4f1c-97f6-8c7129eef60e")
PROGRAM_NAME = "2026年度国家自然科学基金项目"


def load_scholar_package(path: Path) -> dict[str, object]:
    package = json.loads(path.read_text(encoding="utf-8"))
    manifest = package["manifest"]
    scholars = package["scholars"]
    if manifest["synthetic"] is not False:
        raise ValueError("NSFC projects must be derived from a non-synthetic scholar package")
    if manifest["unique_scholars"] != 58 or len(scholars) != 58:
        raise ValueError("the controlled 2026 NSFC project slice requires exactly 58 awardees")
    if len({item["object_id"] for item in scholars}) != len(scholars):
        raise ValueError("duplicate awardee object identifiers")
    if len({item["canonical_name"] for item in scholars}) != len(scholars):
        raise ValueError("duplicate awardee names require identity resolution")
    return package


def project_records(package: dict[str, object]) -> list[dict[str, object]]:
    dataset_version = package["manifest"]["dataset_version"]
    records: list[dict[str, object]] = []
    for scholar in package["scholars"]:
        person_id = UUID(scholar["object_id"])
        name = scholar["canonical_name"]
        key = f"{dataset_version}:nsfc-project:{person_id}"
        records.append(
            {
                "project_id": uuid5(PROJECT_NAMESPACE, key),
                "person_id": person_id,
                "name": name,
                "canonical_name": f"{name} | 2026年度国家自然科学基金获批项目 (项目名称待补)",
                "external_id": f"NSFC26-PROJECT-{scholar['source_order']:04d}",
                "source_rows": scholar["source_excel_rows"],
                "reference_id": uuid5(PROJECT_NAMESPACE, f"{key}:source-reference"),
                "evidence_id": uuid5(PROJECT_NAMESPACE, f"{key}:evidence"),
                "lead_relation_id": uuid5(PROJECT_NAMESPACE, f"{key}:lead-relation"),
                "program_relation_id": uuid5(PROJECT_NAMESPACE, f"{key}:program-relation"),
                "object_event_id": uuid5(PROJECT_NAMESPACE, f"{key}:object-event"),
                "lead_event_id": uuid5(PROJECT_NAMESPACE, f"{key}:lead-event"),
                "program_event_id": uuid5(PROJECT_NAMESPACE, f"{key}:program-event"),
                "audit_event_id": uuid5(PROJECT_NAMESPACE, f"{key}:audit"),
            }
        )
    return records


def import_projects(package: dict[str, object], database_url: str, actor_id: UUID) -> dict[str, int]:
    manifest = package["manifest"]
    dataset_version = manifest["dataset_version"]
    source_system_id = UUID(manifest["source_system_id"])
    records = project_records(package)
    inserted_projects = 0
    inserted_relations = 0

    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        with connection.transaction():
            connection.execute("SELECT set_config('smartlib.actor_id', %s, true)", (str(actor_id),))
            people = connection.execute(
                """SELECT object_id, canonical_name FROM smartlib.knowledge_object
                    WHERE object_id = ANY(%s) AND object_type = 'person'""",
                ([record["person_id"] for record in records],),
            ).fetchall()
            found_people = {row["object_id"]: row["canonical_name"] for row in people}
            missing = [record["name"] for record in records if record["person_id"] not in found_people]
            mismatched = [
                record["name"]
                for record in records
                if found_people.get(record["person_id"]) not in {None, record["name"]}
            ]
            if missing or mismatched:
                raise ValueError(f"awardee reconciliation failed: missing={missing}, mismatched={mismatched}")

            program_attributes = {
                "year": 2026,
                "record_kind": "annual_funding_program",
                "funding_scheme": "国家自然科学基金",
                "funding_agency": "国家自然科学基金委员会",
                "program_level": "national",
                "project_state": "information_pending",
                "metadata_status": "pending_enrichment",
                "official_guide_title": "2026年度国家自然科学基金项目指南",
                "official_source_url": "https://www.nsfc.gov.cn/p1/4201/sqzz.html",
                "official_name_verified_on": "2026-09-04",
                "synthetic": False,
            }
            program_row = connection.execute(
                """INSERT INTO smartlib.knowledge_object
                          (object_id, object_type, canonical_name, description, visibility,
                           quality_state, review_state, attributes, created_by)
                     VALUES (%s, 'funding_program', %s, %s, 'restricted',
                             'unverified', 'pending', %s, %s)
                     ON CONFLICT (object_id) DO UPDATE SET
                         object_type = 'funding_program',
                         canonical_name = EXCLUDED.canonical_name,
                         description = EXCLUDED.description,
                         attributes = smartlib.knowledge_object.attributes || EXCLUDED.attributes,
                         version = smartlib.knowledge_object.version + 1
                     WHERE smartlib.knowledge_object.object_type <> 'funding_program'
                        OR smartlib.knowledge_object.canonical_name <> EXCLUDED.canonical_name
                     RETURNING object_id, version""",
                (
                    ANNUAL_PROGRAM_ID,
                    PROGRAM_NAME,
                    (
                        "国家自然科学基金委员会2026年度项目的年度资助计划入口; "
                        "具体获批项目作为独立项目对象归入本计划。"
                    ),
                    Jsonb(program_attributes),
                    actor_id,
                ),
            ).fetchone()
            program_changed = program_row is not None
            current_program = connection.execute(
                "SELECT object_type, version FROM smartlib.knowledge_object WHERE object_id = %s",
                (ANNUAL_PROGRAM_ID,),
            ).fetchone()
            if current_program is None or current_program["object_type"] != "funding_program":
                raise ValueError("annual funding programme was not established correctly")
            if program_changed:
                connection.execute(
                    """INSERT INTO smartlib.outbox_event
                              (event_id, aggregate_type, aggregate_id, event_type,
                               event_version, payload, trace_id)
                         VALUES (%s, 'knowledge_object', %s, 'knowledge.object.updated',
                                 %s, %s, %s)
                         ON CONFLICT (event_id) DO NOTHING""",
                    (
                        uuid5(PROJECT_NAMESPACE, f"{dataset_version}:annual-program:event"),
                        ANNUAL_PROGRAM_ID,
                        current_program["version"],
                        Jsonb({"object_id": str(ANNUAL_PROGRAM_ID), "version": current_program["version"]}),
                        dataset_version,
                    ),
                )

            program_evidence_id = uuid5(PROJECT_NAMESPACE, f"{dataset_version}:annual-program:evidence")
            connection.execute(
                """INSERT INTO smartlib.evidence_record
                          (evidence_id, object_id, evidence_type, citation, excerpt, visibility,
                           metadata, created_by)
                     VALUES (%s, %s, 'business_record', %s, %s, 'campus', %s, %s)
                     ON CONFLICT (evidence_id) DO NOTHING""",
                (
                    program_evidence_id,
                    ANNUAL_PROGRAM_ID,
                    "国家自然科学基金委员会:《2026年度国家自然科学基金项目指南》",
                    "国家自然科学基金委员会发布2026年度项目指南, 作为年度资助计划名称与范围的来源。",
                    Jsonb(
                        {
                            "source_url": "https://www.nsfc.gov.cn/p1/4201/sqzz.html",
                            "guide_pdf_url": "https://www.nsfc.gov.cn/u/cms/www/202601/190844586k0w.pdf",
                            "verified_on": "2026-09-04",
                        }
                    ),
                    actor_id,
                ),
            )

            for record in records:
                project_attributes = {
                    "year": 2026,
                    "record_kind": "individual_grant",
                    "project_title_status": "pending",
                    "grant_number_status": "pending",
                    "project_type_status": "pending",
                    "funding_amount_status": "pending",
                    "duration_status": "pending",
                    "principal_investigator_person_id": str(record["person_id"]),
                    "principal_investigator_name": record["name"],
                    "funding_program_id": str(ANNUAL_PROGRAM_ID),
                    "dataset_id": manifest["dataset_id"],
                    "dataset_version": dataset_version,
                    "source_role": "获批人",
                    "synthetic": False,
                }
                inserted = connection.execute(
                    """INSERT INTO smartlib.knowledge_object
                              (object_id, object_type, canonical_name, description, visibility,
                               quality_state, review_state, attributes, created_by)
                         VALUES (%s, 'project', %s, %s, 'restricted',
                                 'unverified', 'pending', %s, %s)
                         ON CONFLICT (object_id) DO NOTHING""",
                    (
                        record["project_id"],
                        record["canonical_name"],
                        (
                            f"{record['name']}对应的2026年度国家自然科学基金获批项目; "
                            "项目题名、批准号、类别、经费和期限待补。"
                        ),
                        Jsonb(project_attributes),
                        actor_id,
                    ),
                ).rowcount
                inserted_projects += inserted
                current = connection.execute(
                    """SELECT object_type, attributes FROM smartlib.knowledge_object
                        WHERE object_id = %s""",
                    (record["project_id"],),
                ).fetchone()
                if (
                    current is None
                    or current["object_type"] != "project"
                    or current["attributes"].get("principal_investigator_person_id")
                    != str(record["person_id"])
                ):
                    raise ValueError(f"project identity mismatch for {record['name']}")

                row_list = ",".join(str(row) for row in record["source_rows"])
                reference_metadata = {
                    "dataset_version": dataset_version,
                    "awardee_name": record["name"],
                    "excel_rows": record["source_rows"],
                    "inference_boundary": "用户确认每位获批人对应一项独立项目; 项目详情待正式立项清单补充",
                    "synthetic": False,
                }
                connection.execute(
                    """INSERT INTO smartlib.source_reference
                              (source_reference_id, object_id, source_system_id, external_id,
                               source_version, observed_at, payload_checksum, raw_object_uri,
                               metadata, version)
                         VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 1)
                         ON CONFLICT (source_reference_id) DO NOTHING""",
                    (
                        record["reference_id"],
                        record["project_id"],
                        source_system_id,
                        record["external_id"],
                        dataset_version,
                        manifest["source_file_modified_at"],
                        manifest["source_file_sha256"],
                        f"{manifest['source_file']}#sheet={manifest['sheet']}&column={manifest['name_column']}&rows={row_list}",
                        Jsonb(reference_metadata),
                    ),
                )
                connection.execute(
                    """INSERT INTO smartlib.evidence_record
                              (evidence_id, object_id, source_reference_id, evidence_type,
                               citation, excerpt, visibility, license_tags, metadata, created_by)
                         VALUES (%s, %s, %s, 'business_record', %s, %s, 'restricted', %s, %s, %s)
                         ON CONFLICT (evidence_id) DO NOTHING""",
                    (
                        record["evidence_id"],
                        record["project_id"],
                        record["reference_id"],
                        f"{manifest['source_name']} / {manifest['sheet']} / B列“获批人” / Excel行{row_list}",
                        f"获批人: {record['name']}。当前材料未提供项目题名、批准号和项目类别。",
                        manifest["license_tags"],
                        Jsonb(reference_metadata),
                        actor_id,
                    ),
                )

                for relation_id, subject_id, predicate, object_id, event_id in (
                    (
                        record["lead_relation_id"],
                        record["person_id"],
                        "person.leads_project",
                        record["project_id"],
                        record["lead_event_id"],
                    ),
                    (
                        record["program_relation_id"],
                        record["project_id"],
                        "project.under_program",
                        ANNUAL_PROGRAM_ID,
                        record["program_event_id"],
                    ),
                ):
                    relation_inserted = connection.execute(
                        """INSERT INTO smartlib.relation_assertion
                                  (relation_id, subject_id, predicate, object_id, fact_class,
                                   confidence, visibility, review_state, created_by)
                             VALUES (%s, %s, %s, %s, 'human_confirmed', 1.0,
                                     'restricted', 'approved', %s)
                             ON CONFLICT (relation_id) DO NOTHING""",
                        (relation_id, subject_id, predicate, object_id, actor_id),
                    ).rowcount
                    inserted_relations += relation_inserted
                    connection.execute(
                        """INSERT INTO smartlib.relation_evidence (relation_id, evidence_id)
                           VALUES (%s, %s) ON CONFLICT DO NOTHING""",
                        (relation_id, record["evidence_id"]),
                    )
                    if relation_inserted:
                        connection.execute(
                            """INSERT INTO smartlib.outbox_event
                                      (event_id, aggregate_type, aggregate_id, event_type,
                                       event_version, payload, trace_id)
                                 VALUES (%s, 'relation_assertion', %s,
                                         'knowledge.relation.imported', 1, %s, %s)
                                 ON CONFLICT (event_id) DO NOTHING""",
                            (
                                event_id,
                                relation_id,
                                Jsonb({"relation_id": str(relation_id), "version": 1}),
                                dataset_version,
                            ),
                        )

                if inserted:
                    connection.execute(
                        """INSERT INTO smartlib.outbox_event
                                  (event_id, aggregate_type, aggregate_id, event_type,
                                   event_version, payload, trace_id)
                             VALUES (%s, 'knowledge_object', %s,
                                     'knowledge.object.imported', 1, %s, %s)
                             ON CONFLICT (event_id) DO NOTHING""",
                        (
                            record["object_event_id"],
                            record["project_id"],
                            Jsonb({"object_id": str(record["project_id"]), "version": 1}),
                            dataset_version,
                        ),
                    )
                    connection.execute(
                        """INSERT INTO audit.audit_event
                                  (event_id, actor_id, action, resource_type, resource_id,
                                   decision, trace_id, details)
                             VALUES (%s, %s, 'controlled_file.nsfc_project_imported',
                                     'knowledge_object', %s, 'recorded', %s, %s)
                             """,
                        (
                            record["audit_event_id"],
                            actor_id,
                            str(record["project_id"]),
                            dataset_version,
                            Jsonb({"awardee_name": record["name"], "synthetic": False}),
                        ),
                    )

            counts = connection.execute(
                """SELECT
                     (SELECT count(*) FROM smartlib.knowledge_object
                       WHERE object_type = 'funding_program' AND object_id = %s) AS programmes,
                     (SELECT count(*) FROM smartlib.knowledge_object
                       WHERE object_type = 'project'
                         AND attributes ->> 'dataset_version' = %s
                         AND attributes ->> 'record_kind' = 'individual_grant') AS projects,
                     (SELECT count(*) FROM smartlib.relation_assertion
                       WHERE predicate = 'person.leads_project'
                         AND object_id = ANY(%s)) AS lead_relations,
                     (SELECT count(*) FROM smartlib.relation_assertion
                       WHERE predicate = 'project.under_program'
                         AND object_id = %s) AS programme_relations""",
                (
                    ANNUAL_PROGRAM_ID,
                    dataset_version,
                    ([record["project_id"] for record in records]),
                    ANNUAL_PROGRAM_ID,
                ),
            ).fetchone()
            if counts is None or counts != {
                "programmes": 1,
                "projects": 58,
                "lead_relations": 58,
                "programme_relations": 58,
            }:
                raise ValueError(f"NSFC project import reconciliation failed: {counts}")
            return {
                "inserted_projects": inserted_projects,
                "inserted_relations": inserted_relations,
                **counts,
            }


def main() -> None:
    parser = argparse.ArgumentParser(description="Import 2026 NSFC programme and awardee projects")
    parser.add_argument("--scholars-package", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    package = load_scholar_package(args.scholars_package)
    records = project_records(package)
    if not args.apply:
        print(
            json.dumps(
                {
                    "status": "validated",
                    "annual_program_id": str(ANNUAL_PROGRAM_ID),
                    "projects": len(records),
                    "lead_relations": len(records),
                    "programme_relations": len(records),
                },
                ensure_ascii=False,
            )
        )
        return
    result = import_projects(
        package,
        os.environ["SMARTLIB_DATABASE_URL"],
        UUID(os.environ["SMARTLIB_DEV_ACTOR_ID"]),
    )
    print(json.dumps({"status": "applied", **result}, ensure_ascii=False))


if __name__ == "__main__":
    main()
