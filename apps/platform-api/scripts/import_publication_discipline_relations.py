#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4, uuid5

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

NAMESPACE = UUID("6e0e7325-691f-4a85-8eb8-a6e63be6a978")
PREDICATE = "publication.classified_as_discipline"
EXPECTED_SCHEMES = {
    "MOE_GRADUATE_DISCIPLINE_2022",
    "NSFC_APPLICATION_CODE_2026",
    "GBT_13745_2009",
}


def load_review(path: Path) -> dict[str, Any]:
    review = json.loads(path.read_text(encoding="utf-8"))
    manifest = review["manifest"]
    publications = review["publications"]
    if manifest["database_write_state"] != "preview_only_not_applied":
        raise ValueError("只允许导入尚未应用的论文-学科预览包")
    if manifest["source_import_rows"] != 283 or manifest["unique_publications"] != 271:
        raise ValueError("论文范围必须对账为283条来源记录和271个唯一论文对象")
    if manifest["fulltexts_read"] != 271 or len(publications) != 271:
        raise ValueError("必须成功读取全部271份正式论文全文")
    publication_ids = [UUID(item["publication_id"]) for item in publications]
    if len(set(publication_ids)) != 271:
        raise ValueError("预览包中存在重复论文对象")
    for publication in publications:
        primary = publication["classification"]["primary_by_scheme"]
        if set(primary) != EXPECTED_SCHEMES:
            raise ValueError(f"论文缺少三体系主候选: {publication['publication_id']}")
        for scheme, candidate in primary.items():
            if candidate["scheme"] != scheme or candidate["rank"] != 1:
                raise ValueError(f"主候选结构不一致: {publication['publication_id']}:{scheme}")
            UUID(candidate["discipline_object_id"])
    return review


def relation_records(review: dict[str, Any]) -> list[dict[str, Any]]:
    method_version = review["manifest"]["method_version"]
    dataset_version = review["manifest"]["taxonomy_dataset_version"]
    records: list[dict[str, Any]] = []
    for publication in review["publications"]:
        publication_id = UUID(publication["publication_id"])
        candidates_by_scheme: dict[str, list[dict[str, Any]]] = {
            scheme: sorted(
                [item for item in publication["candidates"] if item["scheme"] == scheme],
                key=lambda item: item["rank"],
            )
            for scheme in EXPECTED_SCHEMES
        }
        for scheme in sorted(EXPECTED_SCHEMES):
            primary = publication["classification"]["primary_by_scheme"][scheme]
            relation_id = uuid5(NAMESPACE, f"primary:{publication_id}:{scheme}")
            alternatives = [
                {
                    "rank": item["rank"],
                    "discipline_object_id": item["discipline_object_id"],
                    "code": item["code"],
                    "name": item["name"],
                    "confidence": item["confidence"],
                    "confidence_value": item["confidence_value"],
                    "score": item["score"],
                }
                for item in candidates_by_scheme[scheme]
                if item["rank"] > 1
            ]
            records.append(
                {
                    "relation_id": relation_id,
                    "publication_id": publication_id,
                    "discipline_id": UUID(primary["discipline_object_id"]),
                    "scheme": scheme,
                    "confidence": primary["confidence_value"],
                    "attributes": {
                        "classification_role": "primary",
                        "scheme": scheme,
                        "discipline_code": primary["code"],
                        "discipline_name": primary["name"],
                        "discipline_level": primary["level"],
                        "confidence_label": primary["confidence"],
                        "score": primary["score"],
                        "matched_terms": primary["matched_terms"],
                        "signal_fields": primary["signal_fields"],
                        "rationale": primary["rationale"],
                        "evidence_excerpt": primary["evidence_excerpt"],
                        "alternative_candidates": alternatives,
                        "publication_review_status": publication["classification"]["review_status"],
                        "method_version": method_version,
                        "taxonomy_dataset_version": dataset_version,
                        "fulltext_resource_id": publication["fulltext_resource_id"],
                        "fulltext_checksum": publication["content_checksum"],
                        "verification_task_state": "deferred_not_created",
                    },
                }
            )
    if len(records) != 813:
        raise ValueError(f"应生成813条三体系主关系, 实际为{len(records)}")
    if len({record["relation_id"] for record in records}) != 813:
        raise ValueError("稳定关系标识发生重复")
    return records


def import_relations(review: dict[str, Any], database_url: str, actor_id: UUID) -> dict[str, Any]:
    records = relation_records(review)
    method_version = review["manifest"]["method_version"]
    taxonomy_dataset_version = review["manifest"]["taxonomy_dataset_version"]
    trace_id = f"publication-discipline:{method_version}:{datetime.now(UTC).isoformat()}"
    inserted = 0
    updated = 0
    unchanged = 0
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        with connection.transaction():
            connection.execute("SELECT set_config('smartlib.actor_id', %s, true)", (str(actor_id),))
            publication_ids = [record["publication_id"] for record in records[::3]]
            discipline_ids = [record["discipline_id"] for record in records]
            endpoint_rows = connection.execute(
                """SELECT object_id,object_type,attributes FROM smartlib.knowledge_object
                    WHERE object_id = ANY(%s)""",
                ([*publication_ids, *discipline_ids],),
            ).fetchall()
            endpoints = {row["object_id"]: row for row in endpoint_rows}
            missing_publications = [value for value in publication_ids if value not in endpoints]
            missing_disciplines = [value for value in discipline_ids if value not in endpoints]
            if missing_publications or missing_disciplines:
                raise ValueError(
                    f"关系端点缺失: publications={missing_publications}, disciplines={missing_disciplines}"
                )
            if any(endpoints[value]["object_type"] != "publication" for value in publication_ids):
                raise ValueError("论文端点对象类型不正确")
            if any(endpoints[value]["object_type"] != "discipline" for value in discipline_ids):
                raise ValueError("学科端点对象类型不正确")

            fulltext_rows = connection.execute(
                """SELECT DISTINCT ON (resource.publication_id)
                          resource.publication_id,resource.fulltext_resource_id,
                          supplement.evidence_id
                     FROM smartlib.publication_fulltext_resource resource
                     JOIN smartlib.change_submission supplement
                       ON supplement.submission_id=resource.submission_id
                    WHERE resource.publication_id=ANY(%s)
                      AND resource.extraction_state='extracted'
                    ORDER BY resource.publication_id,resource.created_at DESC""",
                (publication_ids,),
            ).fetchall()
            evidence_by_publication = {
                row["publication_id"]: (row["fulltext_resource_id"], row["evidence_id"])
                for row in fulltext_rows
            }
            if len(evidence_by_publication) != 271:
                raise ValueError(f"全文证据应覆盖271篇论文, 实际为{len(evidence_by_publication)}")

            for record in records:
                expected_resource_id = UUID(record["attributes"]["fulltext_resource_id"])
                resource_id, evidence_id = evidence_by_publication[record["publication_id"]]
                if resource_id != expected_resource_id:
                    raise ValueError(f"正式全文版本已变化: {record['publication_id']}")
                row = connection.execute(
                    """INSERT INTO smartlib.relation_assertion
                              (relation_id,subject_id,predicate,object_id,fact_class,confidence,
                               visibility,license_tags,review_state,model_version,attributes,created_by)
                         VALUES (%s,%s,%s,%s,'algorithmic_inference',%s,'restricted',
                                 ARRAY['local-fulltext','official-public-source'],'pending',%s,%s,%s)
                         ON CONFLICT (relation_id) DO UPDATE SET
                             object_id=excluded.object_id,
                             fact_class=excluded.fact_class,
                             confidence=excluded.confidence,
                             visibility=excluded.visibility,
                             license_tags=excluded.license_tags,
                             review_state='pending',
                             model_version=excluded.model_version,
                             attributes=excluded.attributes,
                             version=smartlib.relation_assertion.version+1
                         WHERE smartlib.relation_assertion.object_id IS DISTINCT FROM excluded.object_id
                            OR smartlib.relation_assertion.confidence IS DISTINCT FROM excluded.confidence
                            OR smartlib.relation_assertion.review_state <> 'pending'
                            OR smartlib.relation_assertion.model_version
                               IS DISTINCT FROM excluded.model_version
                            OR smartlib.relation_assertion.attributes IS DISTINCT FROM excluded.attributes
                         RETURNING version,(xmax=0) AS was_inserted""",
                    (
                        record["relation_id"],
                        record["publication_id"],
                        PREDICATE,
                        record["discipline_id"],
                        record["confidence"],
                        method_version,
                        Jsonb(record["attributes"]),
                        actor_id,
                    ),
                ).fetchone()
                if row is None:
                    unchanged += 1
                    version_row = connection.execute(
                        "SELECT version FROM smartlib.relation_assertion WHERE relation_id=%s",
                        (record["relation_id"],),
                    ).fetchone()
                    version = int(version_row["version"])
                else:
                    version = int(row["version"])
                    if row["was_inserted"]:
                        inserted += 1
                    else:
                        updated += 1
                    event_id = uuid5(NAMESPACE, f"event:{record['relation_id']}:v{version}")
                    connection.execute(
                        """INSERT INTO smartlib.outbox_event
                                  (event_id,aggregate_type,aggregate_id,event_type,event_version,
                                   payload,trace_id)
                             VALUES (%s,'relation_assertion',%s,'knowledge.relation.imported',
                                     %s,%s,%s)
                             ON CONFLICT (event_id) DO NOTHING""",
                        (
                            event_id,
                            record["relation_id"],
                            version,
                            Jsonb(
                                {
                                    "relation_id": str(record["relation_id"]),
                                    "version": version,
                                    "predicate": PREDICATE,
                                    "scheme": record["scheme"],
                                }
                            ),
                            trace_id,
                        ),
                    )
                connection.execute(
                    """INSERT INTO smartlib.relation_evidence (relation_id,evidence_id)
                         VALUES (%s,%s) ON CONFLICT DO NOTHING""",
                    (record["relation_id"], evidence_id),
                )

            counts = connection.execute(
                """SELECT count(*) AS relations,
                          count(*) FILTER (WHERE review_state='pending') AS pending,
                          count(DISTINCT subject_id) AS publications,
                          count(DISTINCT attributes->>'scheme') AS schemes,
                          count(*) FILTER (
                              WHERE attributes->>'verification_task_state'='deferred_not_created'
                          ) AS verification_deferred
                     FROM smartlib.relation_assertion
                    WHERE predicate=%s AND system_to='infinity'""",
                (PREDICATE,),
            ).fetchone()
            evidence_links = connection.execute(
                """SELECT count(*) AS count FROM smartlib.relation_evidence link
                     JOIN smartlib.relation_assertion relation USING (relation_id)
                    WHERE relation.predicate=%s AND relation.system_to='infinity'""",
                (PREDICATE,),
            ).fetchone()["count"]
            expected_counts = {
                "relations": 813,
                "pending": 813,
                "publications": 271,
                "schemes": 3,
                "verification_deferred": 813,
            }
            actual_counts = {key: counts[key] for key in expected_counts}
            if actual_counts != expected_counts or evidence_links != 813:
                raise ValueError(
                    "导入对账失败: "
                    f"actual={actual_counts}, evidence_links={evidence_links}, "
                    f"expected={expected_counts}"
                )
            by_scheme = dict(Counter(record["scheme"] for record in records))
            connection.execute(
                """INSERT INTO audit.audit_event
                          (event_id,actor_id,action,resource_type,resource_id,
                           decision,trace_id,details)
                     VALUES (%s,%s,'controlled_file.publication_disciplines_imported',
                             'relation_assertion',%s,'recorded',%s,%s)""",
                (
                    uuid4(),
                    actor_id,
                    PREDICATE,
                    trace_id,
                    Jsonb(
                        {
                            "method_version": method_version,
                            "taxonomy_dataset_version": taxonomy_dataset_version,
                            "inserted": inserted,
                            "updated": updated,
                            "unchanged": unchanged,
                            "counts": actual_counts,
                            "evidence_links": evidence_links,
                            "by_scheme": by_scheme,
                            "verification_tasks_created": 0,
                        }
                    ),
                ),
            )
    return {
        "predicate": PREDICATE,
        "inserted": inserted,
        "updated": updated,
        "unchanged": unchanged,
        "counts": actual_counts,
        "evidence_links": evidence_links,
        "by_scheme": by_scheme,
        "verification_tasks_created": 0,
        "trace_id": trace_id,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="导入论文到三套学科体系的主候选关系")
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    review = load_review(args.review)
    preview = {
        "method_version": review["manifest"]["method_version"],
        "relations": len(relation_records(review)),
        "review_state": "pending",
        "verification_tasks_created": 0,
    }
    if not args.apply:
        print(json.dumps({"mode": "dry-run", **preview}, ensure_ascii=False, indent=2))
        return
    result = import_relations(
        review,
        os.environ["SMARTLIB_DATABASE_URL"],
        UUID(os.environ["SMARTLIB_DEV_ACTOR_ID"]),
    )
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
