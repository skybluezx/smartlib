"""Create canonical journal objects and publication.published_in relations."""

from __future__ import annotations

import argparse
import os
from collections import Counter
from uuid import UUID, uuid5

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from smartlib_platform.journals.normalization import journal_key, normalized_title

RULE_VERSION = "publication-journal-materialization-v1"
NAMESPACE = UUID("925415ad-c26f-458c-8d1d-f82b56da9c59")


def emit_event(connection, aggregate_type: str, aggregate_id: UUID, version: int) -> None:
    event_id = uuid5(NAMESPACE, f"event:{aggregate_type}:{aggregate_id}:v{version}")
    connection.execute(
        """INSERT INTO smartlib.outbox_event
                  (event_id,aggregate_type,aggregate_id,event_type,event_version,payload,trace_id)
             VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (event_id) DO NOTHING""",
        (
            event_id,
            aggregate_type,
            aggregate_id,
            f"knowledge.{aggregate_type}.updated",
            version,
            Jsonb({"id": str(aggregate_id), "version": version}),
            RULE_VERSION,
        ),
    )


def materialize(connection, actor_id: UUID, *, apply: bool) -> dict[str, int]:
    publications = connection.execute(
        """SELECT metadata.publication_id,metadata.journal_name,metadata.journal_abbreviation,
                         metadata.issn,metadata.eissn,metadata.publication_year
                    FROM smartlib.publication_metadata metadata
                    JOIN smartlib.knowledge_object publication
                      ON publication.object_id=metadata.publication_id
                   WHERE publication.object_type='publication'
                     AND publication.system_to='infinity'::timestamptz
                     AND metadata.journal_name IS NOT NULL
                     AND length(btrim(metadata.journal_name))>0
                   ORDER BY metadata.publication_id"""
    ).fetchall()
    counters: Counter[str] = Counter(publications=len(publications))
    for publication in publications:
        normalized = normalized_title(publication["journal_name"])
        key = journal_key(publication["journal_name"])
        identity = connection.execute(
            """SELECT journal_id,canonical_title,normalized_title,issn,eissn,knowledge_object_id
                   FROM smartlib.journal_identity
                  WHERE issn=ANY(ARRAY[%s::text,%s::text])
                     OR eissn=ANY(ARRAY[%s::text,%s::text])
                     OR lower(btrim(normalized_title))=%s
                     OR EXISTS (
                         SELECT 1 FROM smartlib.journal_name_variant variant
                          WHERE variant.journal_id=journal_identity.journal_id
                            AND variant.normalized_name=%s
                     )
                  ORDER BY CASE
                    WHEN issn=%s OR eissn=%s THEN 0
                    WHEN issn=%s OR eissn=%s THEN 1
                    ELSE 2 END,
                    (SELECT count(*) FROM smartlib.journal_metric_record record
                      WHERE record.journal_id=journal_identity.journal_id) DESC,
                    journal_id
                  LIMIT 1""",
            (
                publication["issn"], publication["eissn"],
                publication["issn"], publication["eissn"], normalized, key,
                publication["issn"], publication["issn"],
                publication["eissn"], publication["eissn"],
            ),
        ).fetchone()
        if identity is None:
            counters["journal_identities_created"] += 1
            if not apply:
                continue
            identity = connection.execute(
                """INSERT INTO smartlib.journal_identity
                          (canonical_title,normalized_title,issn,eissn,created_by)
                     VALUES (%s,%s,%s,%s,%s)
                     RETURNING journal_id,canonical_title,normalized_title,issn,eissn,
                               knowledge_object_id""",
                (
                    publication["journal_name"], normalized, publication["issn"],
                    publication["eissn"], actor_id,
                ),
            ).fetchone()
        if not apply:
            counters["journal_objects_planned"] += int(identity["knowledge_object_id"] is None)
            counters["relations_planned"] += 1
            continue

        object_id = identity["knowledge_object_id"] or identity["journal_id"]
        object_row = connection.execute(
            """INSERT INTO smartlib.knowledge_object
                      (object_id,object_type,canonical_name,description,visibility,quality_state,
                       review_state,attributes,created_by)
                 VALUES (%s,'journal',%s,%s,'restricted','validated','approved',%s,%s)
                 ON CONFLICT (object_id) DO UPDATE SET
                   canonical_name=excluded.canonical_name,
                   attributes=smartlib.knowledge_object.attributes||excluded.attributes,
                   version=smartlib.knowledge_object.version+1
                 RETURNING version,(xmax=0) AS inserted""",
            (
                object_id,
                identity["canonical_title"],
                "论文发表期刊；年度影响因子与分区通过独立版本化指标记录关联。",  # noqa: RUF001
                Jsonb({
                    "record_kind": "journal",
                    "journal_identity_id": str(identity["journal_id"]),
                    "issn": identity["issn"],
                    "eissn": identity["eissn"],
                    "source": "publication_metadata",
                }),
                actor_id,
            ),
        ).fetchone()
        connection.execute(
            "UPDATE smartlib.journal_identity SET knowledge_object_id=%s WHERE journal_id=%s",
            (object_id, identity["journal_id"]),
        )
        emit_event(connection, "knowledge_object", object_id, int(object_row["version"]))
        counters["journal_objects_created"] += int(object_row["inserted"])

        relation_id = uuid5(NAMESPACE, f"published-in:{publication['publication_id']}:{object_id}")
        relation_row = connection.execute(
            """INSERT INTO smartlib.relation_assertion
                      (relation_id,subject_id,predicate,object_id,fact_class,confidence,visibility,
                       license_tags,review_state,model_version,attributes,created_by)
                 VALUES (%s,%s,'publication.published_in',%s,'business_fact',1,'restricted',
                         ARRAY['publication-metadata'],'approved',%s,%s,%s)
                 ON CONFLICT (subject_id) WHERE predicate='publication.published_in'
                   AND review_state='approved' AND system_to='infinity'::timestamptz
                 DO UPDATE SET object_id=excluded.object_id,
                 attributes=excluded.attributes,review_state='approved',
                 version=smartlib.relation_assertion.version+1
                 RETURNING relation_id,version,(xmax=0) AS inserted""",
            (
                relation_id, publication["publication_id"], object_id, RULE_VERSION,
                Jsonb({
                    "relation_label": "发表于",
                    "publication_year": publication["publication_year"],
                    "journal_name_raw": publication["journal_name"],
                    "match_basis": (
                        "issn" if publication["issn"] and publication["issn"] in
                        {identity["issn"], identity["eissn"]} else
                        "eissn" if publication["eissn"] and publication["eissn"] in
                        {identity["issn"], identity["eissn"]} else "normalized_title"
                    ),
                }),
                actor_id,
            ),
        ).fetchone()
        emit_event(
            connection,
            "relation_assertion",
            relation_row["relation_id"],
            int(relation_row["version"]),
        )
        counters["relations_created"] += int(relation_row["inserted"])
    if apply:
        connection.commit()
    else:
        connection.rollback()
    counters["distinct_journal_objects"] = int(connection.execute(
        "SELECT count(*) FROM smartlib.journal_identity WHERE knowledge_object_id IS NOT NULL"
    ).fetchone()["count"] if apply else counters["journal_objects_planned"])
    return dict(counters)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    database_url = os.environ["SMARTLIB_DATABASE_URL"]
    actor_id = UUID(os.environ.get("SMARTLIB_DEV_ACTOR_ID", "00000000-0000-4000-8000-000000000001"))
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        connection.execute("SELECT set_config('smartlib.actor_id', %s, false)", (str(actor_id),))
        print(materialize(connection, actor_id, apply=args.apply))


if __name__ == "__main__":
    main()
