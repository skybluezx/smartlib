#!/usr/bin/env python3
# ruff: noqa: RUF001
from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
from collections import Counter
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from smartlib_platform.storage.s3 import S3ObjectStore


def load_package(path: Path) -> dict[str, object]:
    package = json.loads(path.read_text(encoding="utf-8"))
    manifest = package["manifest"]
    objects = package["objects"]
    relations = package["relations"]
    if manifest["synthetic"] is not False:
        raise ValueError("学科分类受控导入包不得标记为虚拟数据")
    if manifest["object_counts"] != dict(Counter(item["object_type"] for item in objects)):
        raise ValueError("对象计数不一致")
    if manifest["discipline_counts"] != dict(
        Counter(item["scheme"] for item in objects if item["object_type"] == "discipline")
    ):
        raise ValueError("学科体系计数不一致")
    if manifest["relation_counts"] != dict(Counter(item["predicate"] for item in relations)):
        raise ValueError("关系计数不一致")
    object_ids = {UUID(item["object_id"]) for item in objects}
    if len(object_ids) != len(objects):
        raise ValueError("对象稳定标识重复")
    relation_ids = {UUID(item["relation_id"]) for item in relations}
    if len(relation_ids) != len(relations):
        raise ValueError("关系稳定标识重复")
    if any(item["scheme"] == "GBT_13745_2009" and int(item["level"]) == 3 for item in objects):
        raise ValueError("GB/T三级解析词项不得进入正式导入包")
    for relation in relations:
        if UUID(relation["subject_id"]) not in object_ids or UUID(relation["object_id"]) not in object_ids:
            raise ValueError(f"关系端点不存在: {relation['relation_id']}")
    source_paths = {item["path"] for item in package["source_files"]}
    referenced_paths = {item["source_path"] for item in objects}
    if missing := referenced_paths - source_paths:
        raise ValueError(f"对象引用了未登记的来源文件: {sorted(missing)}")
    return package


def upload_sources(
    package: dict[str, object], source_root: Path, store: S3ObjectStore
) -> tuple[dict[str, str], dict[str, int]]:
    uris: dict[str, str] = {}
    uploaded = 0
    reused = 0
    for item in package["source_files"]:
        relative_path = item["path"]
        path = source_root / relative_path
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest != item["sha256"] or len(data) != item["bytes"]:
            raise ValueError(f"来源文件校验失败: {relative_path}")
        key = f"reference-data/discipline-taxonomies/2026-09-04/{relative_path}"
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        result = store.put_bytes(key, data, content_type)
        uris[relative_path] = result.storage_uri
        if result.created:
            uploaded += 1
        else:
            reused += 1
    return uris, {"uploaded_source_files": uploaded, "reused_source_files": reused}


def import_package(
    package: dict[str, object], database_url: str, actor_id: UUID, source_uris: dict[str, str]
) -> dict[str, int]:
    manifest = package["manifest"]
    dataset_id = manifest["dataset_id"]
    dataset_version = manifest["dataset_version"]
    schemes_by_code = {item["scheme"]: item for item in package["schemes"]}
    source_files = {item["path"]: item for item in package["source_files"]}
    inserted_objects = 0
    inserted_relations = 0

    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        with connection.transaction():
            connection.execute("SELECT set_config('smartlib.actor_id', %s, true)", (str(actor_id),))
            for source in package["source_systems"]:
                connection.execute(
                    """INSERT INTO smartlib.source_system
                              (source_system_id, code, name, owner_department, source_type,
                               authorization_state, metadata)
                         VALUES (%s, %s, %s, %s, %s, %s, %s)
                         ON CONFLICT (code) DO NOTHING""",
                    (
                        UUID(source["source_system_id"]),
                        source["code"],
                        source["name"],
                        source["owner_department"],
                        source["source_type"],
                        source["authorization_state"],
                        Jsonb(
                            {
                                "dataset_id": dataset_id,
                                "dataset_version": dataset_version,
                                "official": True,
                                "synthetic": False,
                            }
                        ),
                    ),
                )
                current = connection.execute(
                    "SELECT source_system_id FROM smartlib.source_system WHERE code = %s",
                    (source["code"],),
                ).fetchone()
                if current is None or current["source_system_id"] != UUID(source["source_system_id"]):
                    raise ValueError(f"来源系统代码已绑定其他标识: {source['code']}")

            for item in package["objects"]:
                object_id = UUID(item["object_id"])
                source_file = source_files[item["source_path"]]
                attributes = {
                    "dataset_id": dataset_id,
                    "dataset_version": dataset_version,
                    "synthetic": False,
                    "official": True,
                    "scheme": item["scheme"],
                    "scheme_code": item["code"],
                    "level": item["level"],
                    "node_type": item["node_type"],
                    "parent_code": item["parent_code"] or None,
                    "source_authority": source_file["authority"],
                    "source_url": source_file["source_url"],
                    **item["attributes"],
                }
                inserted_objects += connection.execute(
                    """INSERT INTO smartlib.knowledge_object
                              (object_id, object_type, canonical_name, description, visibility,
                               quality_state, review_state, attributes, created_by)
                         VALUES (%s, %s, %s, %s, 'public', %s, 'approved', %s, %s)
                         ON CONFLICT (object_id) DO NOTHING""",
                    (
                        object_id,
                        item["object_type"],
                        item["canonical_name"],
                        item["description"],
                        item["quality_state"],
                        Jsonb(attributes),
                        actor_id,
                    ),
                ).rowcount
                current = connection.execute(
                    """SELECT canonical_name, object_type, attributes
                         FROM smartlib.knowledge_object WHERE object_id = %s""",
                    (object_id,),
                ).fetchone()
                if (
                    current is None
                    or current["canonical_name"] != item["canonical_name"]
                    or current["object_type"] != item["object_type"]
                    or current["attributes"].get("dataset_version") != dataset_version
                ):
                    raise ValueError(f"对象身份不一致: {item['scheme']}:{item['code']}")

                connection.execute(
                    """INSERT INTO smartlib.source_reference
                              (source_reference_id, object_id, source_system_id, external_id,
                               source_version, payload_checksum, raw_object_uri, metadata, version)
                         VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 1)
                         ON CONFLICT (source_reference_id) DO NOTHING""",
                    (
                        UUID(item["source_reference_id"]),
                        object_id,
                        UUID(item["source_system_id"]),
                        f"{item['scheme']}:{item['code']}",
                        dataset_version,
                        item["content_checksum"],
                        source_uris[item["source_path"]],
                        Jsonb(
                            {
                                "dataset_id": dataset_id,
                                "dataset_version": dataset_version,
                                "source_path": item["source_path"],
                                "source_url": source_file["source_url"],
                                "source_file_sha256": source_file["sha256"],
                            }
                        ),
                    ),
                )
                connection.execute(
                    """INSERT INTO smartlib.outbox_event
                              (event_id, aggregate_type, aggregate_id, event_type,
                               event_version, payload, trace_id)
                         VALUES (%s, 'knowledge_object', %s, 'knowledge.object.imported', 1, %s, %s)
                         ON CONFLICT (event_id) DO NOTHING""",
                    (
                        UUID(item["outbox_event_id"]),
                        object_id,
                        Jsonb(
                            {
                                "object_id": str(object_id),
                                "version": 1,
                                "dataset_id": dataset_id,
                                "dataset_version": dataset_version,
                            }
                        ),
                        dataset_version,
                    ),
                )

            for scheme_code, scheme in schemes_by_code.items():
                source_file = source_files[scheme["source_path"]]
                evidence_id = UUID(
                    next(
                        relation["evidence_id"]
                        for relation in package["relations"]
                        if relation["scheme"] == scheme_code
                    )
                )
                connection.execute(
                    """INSERT INTO smartlib.evidence_record
                              (evidence_id, object_id, source_reference_id, evidence_type,
                               citation, excerpt, visibility, license_tags, content_checksum,
                               metadata, created_by)
                         VALUES (%s, %s, %s, 'business_record', %s, %s, 'public', %s, %s, %s, %s)
                         ON CONFLICT (evidence_id) DO NOTHING""",
                    (
                        evidence_id,
                        UUID(scheme["object_id"]),
                        UUID(
                            next(
                                item["source_reference_id"]
                                for item in package["objects"]
                                if item["object_id"] == scheme["object_id"]
                            )
                        ),
                        f"{source_file['authority']}：{scheme['name']}",
                        scheme["description"],
                        ["official-public-source"],
                        source_file["sha256"],
                        Jsonb(
                            {
                                "dataset_id": dataset_id,
                                "dataset_version": dataset_version,
                                "source_url": source_file["source_url"],
                                "raw_object_uri": source_uris[scheme["source_path"]],
                            }
                        ),
                        actor_id,
                    ),
                )

            for relation in package["relations"]:
                attributes = {
                    "dataset_id": dataset_id,
                    "dataset_version": dataset_version,
                    "scheme": relation["scheme"],
                    **relation["attributes"],
                }
                inserted_relations += connection.execute(
                    """INSERT INTO smartlib.relation_assertion
                              (relation_id, subject_id, predicate, object_id, fact_class,
                               confidence, visibility, license_tags, review_state, attributes, created_by)
                         VALUES (%s, %s, %s, %s, 'business_fact', 1.0, 'public', %s,
                                 'approved', %s, %s)
                         ON CONFLICT (relation_id) DO NOTHING""",
                    (
                        UUID(relation["relation_id"]),
                        UUID(relation["subject_id"]),
                        relation["predicate"],
                        UUID(relation["object_id"]),
                        ["official-public-source"],
                        Jsonb(attributes),
                        actor_id,
                    ),
                ).rowcount
                connection.execute(
                    """INSERT INTO smartlib.relation_evidence (relation_id, evidence_id)
                         VALUES (%s, %s) ON CONFLICT DO NOTHING""",
                    (UUID(relation["relation_id"]), UUID(relation["evidence_id"])),
                )
                connection.execute(
                    """INSERT INTO smartlib.outbox_event
                              (event_id, aggregate_type, aggregate_id, event_type,
                               event_version, payload, trace_id)
                         VALUES (%s, 'relation_assertion', %s, 'knowledge.relation.imported', 1, %s, %s)
                         ON CONFLICT (event_id) DO NOTHING""",
                    (
                        UUID(relation["outbox_event_id"]),
                        UUID(relation["relation_id"]),
                        Jsonb(
                            {
                                "relation_id": relation["relation_id"],
                                "version": 1,
                                "dataset_id": dataset_id,
                                "dataset_version": dataset_version,
                            }
                        ),
                        dataset_version,
                    ),
                )

            counts = connection.execute(
                """SELECT
                       (SELECT count(*) FROM smartlib.knowledge_object
                         WHERE attributes ->> 'dataset_id' = %s
                           AND attributes ->> 'dataset_version' = %s) AS objects,
                       (SELECT count(*) FROM smartlib.source_reference
                         WHERE metadata ->> 'dataset_id' = %s
                           AND metadata ->> 'dataset_version' = %s) AS source_references,
                       (SELECT count(*) FROM smartlib.relation_assertion
                         WHERE attributes ->> 'dataset_id' = %s
                           AND attributes ->> 'dataset_version' = %s) AS relations,
                       (SELECT count(*) FROM smartlib.evidence_record
                         WHERE metadata ->> 'dataset_id' = %s
                           AND metadata ->> 'dataset_version' = %s) AS evidence_records,
                       (SELECT count(*) FROM smartlib.outbox_event WHERE trace_id = %s) AS outbox_events""",
                (
                    dataset_id,
                    dataset_version,
                    dataset_id,
                    dataset_version,
                    dataset_id,
                    dataset_version,
                    dataset_id,
                    dataset_version,
                    dataset_version,
                ),
            ).fetchone()
            expected = {
                "objects": len(package["objects"]),
                "source_references": len(package["objects"]),
                "relations": len(package["relations"]),
                "evidence_records": len(package["schemes"]),
                "outbox_events": len(package["objects"]) + len(package["relations"]),
            }
            if counts is None or any(counts[key] != value for key, value in expected.items()):
                raise ValueError(f"导入对账失败: actual={counts}, expected={expected}")
            connection.execute(
                """INSERT INTO audit.audit_event
                          (event_id, actor_id, action, resource_type, resource_id,
                           decision, trace_id, details)
                     VALUES (%s, %s, 'controlled_file.discipline_taxonomies_imported',
                             'dataset', %s, 'recorded', %s, %s)
                     """,
                (
                    uuid4(),
                    actor_id,
                    dataset_id,
                    dataset_version,
                    Jsonb(
                        {
                            "dataset_version": dataset_version,
                            "counts": expected,
                            "excluded": manifest["excluded"],
                        }
                    ),
                ),
            )
            return {"inserted_objects": inserted_objects, "inserted_relations": inserted_relations, **counts}


def main() -> None:
    parser = argparse.ArgumentParser(description="导入权威学科分类对象与关系")
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    package = load_package(args.package)
    if not args.apply:
        print(json.dumps({"status": "validated", **package["manifest"]}, ensure_ascii=False))
        return
    store = S3ObjectStore(
        endpoint_url=os.environ["SMARTLIB_S3_ENDPOINT_URL"],
        bucket=os.environ.get("SMARTLIB_REFERENCE_DATA_BUCKET", "smartlib-reference-data"),
        access_key=os.environ["SMARTLIB_S3_ACCESS_KEY"],
        secret_key=os.environ["SMARTLIB_S3_SECRET_KEY"],
        region=os.environ.get("SMARTLIB_S3_REGION", "us-east-1"),
    )
    source_uris, storage_counts = upload_sources(package, args.source_root, store)
    result = import_package(
        package,
        os.environ["SMARTLIB_DATABASE_URL"],
        UUID(os.environ["SMARTLIB_DEV_ACTOR_ID"]),
        source_uris,
    )
    print(json.dumps({"status": "applied", **storage_counts, **result}, ensure_ascii=False))


if __name__ == "__main__":
    main()
