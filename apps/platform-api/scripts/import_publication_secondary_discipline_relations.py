#!/usr/bin/env python3
# ruff: noqa: RUF001
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4, uuid5

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from import_publication_discipline_relations import (  # noqa: E402
    PREDICATE,
    load_review,
)

NAMESPACE = UUID("6e0e7325-691f-4a85-8eb8-a6e63be6a978")
SELECTION_VERSION = "publication-discipline-secondary-v1"
STRONG_SIGNAL_FIELDS = {"题名", "关键词/MeSH", "摘要"}
MIN_SCORE_RATIO = 0.75


def load_taxonomy(path: Path) -> dict[str, Any]:
    package = json.loads(path.read_text(encoding="utf-8"))
    if package["manifest"]["dataset_version"] != "2026-09-04-v1":
        raise ValueError("学科体系版本与论文分类预览不一致")
    return package


def parent_map(package: dict[str, Any]) -> dict[str, str]:
    return {
        relation["subject_id"]: relation["object_id"]
        for relation in package["relations"]
        if relation["predicate"] == "taxonomy.broader"
    }


def ancestors(object_id: str, parents: dict[str, str]) -> set[str]:
    result: set[str] = set()
    current = object_id
    while current in parents and parents[current] not in result:
        current = parents[current]
        result.add(current)
    return result


def hierarchy_related(first: str, second: str, parents: dict[str, str]) -> bool:
    return first in ancestors(second, parents) or second in ancestors(first, parents)


def rationale_set(candidate: dict[str, Any]) -> set[str]:
    return {value for value in candidate["rationale"].split("；") if value}


def is_method_discipline(scheme: str, code: str) -> bool:
    if scheme == "MOE_GRADUATE_DISCIPLINE_2022":
        return code.startswith(("0703", "0805", "0812", "0831"))
    if scheme == "NSFC_APPLICATION_CODE_2026":
        return code.startswith(("F", "B04", "H27", "H28", "C05", "C06", "C10", "A10"))
    return code.startswith(("13041", "15025", "41660", "4306", "4307", "520"))


def secondary_role(scheme: str, primary_code: str, candidate_code: str) -> str:
    if is_method_discipline(scheme, candidate_code):
        return "method"
    if is_method_discipline(scheme, primary_code):
        return "application"
    return "interdisciplinary"


def select_secondary_records(
    review: dict[str, Any], package: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    parents = parent_map(package)
    method_version = review["manifest"]["method_version"]
    dataset_version = review["manifest"]["taxonomy_dataset_version"]
    exclusions: Counter[str] = Counter()
    records: list[dict[str, Any]] = []
    for publication in review["publications"]:
        publication_id = UUID(publication["publication_id"])
        candidates_by_scheme: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for candidate in publication["candidates"]:
            candidates_by_scheme[candidate["scheme"]].append(candidate)
        for scheme, candidates in candidates_by_scheme.items():
            candidates.sort(key=lambda item: item["rank"])
            primary = candidates[0]
            for candidate in candidates[1:]:
                if candidate["confidence"] == "低":
                    exclusions["low_confidence"] += 1
                    continue
                if not STRONG_SIGNAL_FIELDS.intersection(candidate["signal_fields"]):
                    exclusions["fulltext_only_signal"] += 1
                    continue
                score_ratio = candidate["score"] / max(primary["score"], 0.01)
                if score_ratio < MIN_SCORE_RATIO:
                    exclusions["score_ratio_below_0_75"] += 1
                    continue
                if hierarchy_related(
                    primary["discipline_object_id"],
                    candidate["discipline_object_id"],
                    parents,
                ):
                    exclusions["same_hierarchy_branch"] += 1
                    continue
                if rationale_set(candidate) == rationale_set(primary):
                    exclusions["same_topic_different_granularity"] += 1
                    continue
                role = secondary_role(scheme, primary["code"], candidate["code"])
                relation_id = uuid5(
                    NAMESPACE,
                    f"secondary:{publication_id}:{scheme}:{candidate['discipline_object_id']}",
                )
                records.append(
                    {
                        "relation_id": relation_id,
                        "publication_id": publication_id,
                        "discipline_id": UUID(candidate["discipline_object_id"]),
                        "scheme": scheme,
                        "confidence": candidate["confidence_value"],
                        "attributes": {
                            "classification_role": "secondary",
                            "secondary_role": role,
                            "scheme": scheme,
                            "discipline_code": candidate["code"],
                            "discipline_name": candidate["name"],
                            "discipline_level": candidate["level"],
                            "candidate_rank": candidate["rank"],
                            "confidence_label": candidate["confidence"],
                            "score": candidate["score"],
                            "score_ratio_to_primary": round(score_ratio, 4),
                            "matched_terms": candidate["matched_terms"],
                            "signal_fields": candidate["signal_fields"],
                            "rationale": candidate["rationale"],
                            "evidence_excerpt": candidate["evidence_excerpt"],
                            "primary_discipline_object_id": primary["discipline_object_id"],
                            "primary_discipline_code": primary["code"],
                            "selection_version": SELECTION_VERSION,
                            "selection_basis": (
                                "medium_or_high_confidence; metadata_signal; "
                                "score_ratio>=0.75; hierarchy_distinct; topic_distinct"
                            ),
                            "method_version": method_version,
                            "taxonomy_dataset_version": dataset_version,
                            "fulltext_resource_id": publication["fulltext_resource_id"],
                            "fulltext_checksum": publication["content_checksum"],
                            "verification_task_state": "deferred_not_created",
                        },
                    }
                )
    if len(records) != 330:
        raise ValueError(f"交叉关系应对账为330条, 实际为{len(records)}")
    if len({record["relation_id"] for record in records}) != len(records):
        raise ValueError("交叉关系稳定标识重复")
    return records, dict(exclusions)


def import_secondary_relations(
    review: dict[str, Any], package: dict[str, Any], database_url: str, actor_id: UUID
) -> dict[str, Any]:
    records, exclusions = select_secondary_records(review, package)
    trace_id = f"publication-discipline-secondary:{SELECTION_VERSION}:{datetime.now(UTC).isoformat()}"
    inserted = 0
    updated = 0
    unchanged = 0
    publication_ids = sorted({record["publication_id"] for record in records})
    discipline_ids = sorted({record["discipline_id"] for record in records})
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        with connection.transaction():
            connection.execute("SELECT set_config('smartlib.actor_id', %s, true)", (str(actor_id),))
            primary_count = connection.execute(
                """SELECT count(*) AS count FROM smartlib.relation_assertion
                    WHERE predicate=%s AND review_state='pending'
                      AND attributes->>'classification_role'='primary'
                      AND system_to='infinity'""",
                (PREDICATE,),
            ).fetchone()["count"]
            if primary_count != 813:
                raise ValueError(f"主学科关系必须先完整写入813条, 实际为{primary_count}")
            endpoint_rows = connection.execute(
                """SELECT object_id,object_type FROM smartlib.knowledge_object
                    WHERE object_id=ANY(%s)""",
                ([*publication_ids, *discipline_ids],),
            ).fetchall()
            endpoints = {row["object_id"]: row["object_type"] for row in endpoint_rows}
            if any(endpoints.get(value) != "publication" for value in publication_ids):
                raise ValueError("交叉关系包含无效论文端点")
            if any(endpoints.get(value) != "discipline" for value in discipline_ids):
                raise ValueError("交叉关系包含无效学科端点")
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
            if len(evidence_by_publication) != len(publication_ids):
                raise ValueError("交叉关系论文未被正式全文证据完整覆盖")

            for record in records:
                resource_id, evidence_id = evidence_by_publication[record["publication_id"]]
                if resource_id != UUID(record["attributes"]["fulltext_resource_id"]):
                    raise ValueError(f"正式全文版本已变化: {record['publication_id']}")
                row = connection.execute(
                    """INSERT INTO smartlib.relation_assertion
                              (relation_id,subject_id,predicate,object_id,fact_class,confidence,
                               visibility,license_tags,review_state,model_version,attributes,created_by)
                         VALUES (%s,%s,%s,%s,'algorithmic_inference',%s,'restricted',
                                 ARRAY['local-fulltext','official-public-source'],'pending',%s,%s,%s)
                         ON CONFLICT (relation_id) DO UPDATE SET
                             object_id=excluded.object_id,
                             confidence=excluded.confidence,
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
                        SELECTION_VERSION,
                        Jsonb(record["attributes"]),
                        actor_id,
                    ),
                ).fetchone()
                if row is None:
                    unchanged += 1
                else:
                    if row["was_inserted"]:
                        inserted += 1
                    else:
                        updated += 1
                    event_id = uuid5(
                        NAMESPACE,
                        f"secondary-event:{record['relation_id']}:v{int(row['version'])}",
                    )
                    connection.execute(
                        """INSERT INTO smartlib.outbox_event
                                  (event_id,aggregate_type,aggregate_id,event_type,event_version,
                                   payload,trace_id)
                             VALUES (%s,'relation_assertion',%s,'knowledge.relation.imported',
                                     %s,%s,%s) ON CONFLICT (event_id) DO NOTHING""",
                        (
                            event_id,
                            record["relation_id"],
                            int(row["version"]),
                            Jsonb(
                                {
                                    "relation_id": str(record["relation_id"]),
                                    "version": int(row["version"]),
                                    "predicate": PREDICATE,
                                    "classification_role": "secondary",
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
                """SELECT count(*) AS total,
                          count(*) FILTER (
                              WHERE attributes->>'classification_role'='primary'
                          ) AS primary_relations,
                          count(*) FILTER (
                              WHERE attributes->>'classification_role'='secondary'
                          ) AS secondary_relations,
                          count(DISTINCT subject_id) AS publications,
                          count(*) FILTER (WHERE review_state='pending') AS pending
                     FROM smartlib.relation_assertion
                    WHERE predicate=%s AND system_to='infinity'""",
                (PREDICATE,),
            ).fetchone()
            actual = dict(counts)
            expected = {
                "total": 1143,
                "primary_relations": 813,
                "secondary_relations": 330,
                "publications": 271,
                "pending": 1143,
            }
            if actual != expected:
                raise ValueError(f"一对多关系对账失败: actual={actual}, expected={expected}")
            evidence_links = connection.execute(
                """SELECT count(*) AS count FROM smartlib.relation_evidence link
                     JOIN smartlib.relation_assertion relation USING (relation_id)
                    WHERE relation.predicate=%s AND relation.system_to='infinity'""",
                (PREDICATE,),
            ).fetchone()["count"]
            if evidence_links != 1143:
                raise ValueError(f"关系证据链接应为1143条, 实际为{evidence_links}")
            by_scheme = dict(Counter(record["scheme"] for record in records))
            by_role = dict(Counter(record["attributes"]["secondary_role"] for record in records))
            connection.execute(
                """INSERT INTO audit.audit_event
                          (event_id,actor_id,action,resource_type,resource_id,
                           decision,trace_id,details)
                     VALUES (%s,%s,'controlled_file.publication_secondary_disciplines_imported',
                             'relation_assertion',%s,'recorded',%s,%s)""",
                (
                    uuid4(),
                    actor_id,
                    PREDICATE,
                    trace_id,
                    Jsonb(
                        {
                            "selection_version": SELECTION_VERSION,
                            "inserted": inserted,
                            "updated": updated,
                            "unchanged": unchanged,
                            "counts": actual,
                            "evidence_links": evidence_links,
                            "by_scheme": by_scheme,
                            "by_secondary_role": by_role,
                            "exclusions": exclusions,
                            "verification_tasks_created": 0,
                        }
                    ),
                ),
            )
    return {
        "predicate": PREDICATE,
        "selection_version": SELECTION_VERSION,
        "inserted": inserted,
        "updated": updated,
        "unchanged": unchanged,
        "counts": actual,
        "evidence_links": evidence_links,
        "secondary_by_scheme": by_scheme,
        "secondary_by_role": by_role,
        "excluded_candidates": exclusions,
        "verification_tasks_created": 0,
        "trace_id": trace_id,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="筛选并导入论文的一对多交叉学科关系")
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--taxonomy-package", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    review = load_review(args.review)
    package = load_taxonomy(args.taxonomy_package)
    records, exclusions = select_secondary_records(review, package)
    if not args.apply:
        print(
            json.dumps(
                {
                    "mode": "dry-run",
                    "secondary_relations": len(records),
                    "by_scheme": dict(Counter(record["scheme"] for record in records)),
                    "by_role": dict(Counter(record["attributes"]["secondary_role"] for record in records)),
                    "exclusions": exclusions,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    result = import_secondary_relations(
        review,
        package,
        os.environ["SMARTLIB_DATABASE_URL"],
        UUID(os.environ["SMARTLIB_DEV_ACTOR_ID"]),
    )
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
