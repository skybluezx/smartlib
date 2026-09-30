"""Match publications to published journal metrics using the publication year only."""

from __future__ import annotations

import argparse
import os
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

RULE_VERSION = "publication-year-journal-metric-match-v1"


def match_metrics(connection, actor_id: UUID, *, apply: bool) -> dict[str, int]:
    rows = connection.execute(
        """SELECT publication.object_id AS publication_id,record.record_id,
                         release.metric_system,release.metric_year,
                         CASE
                           WHEN metadata.issn IS NOT NULL
                            AND metadata.issn IN (identity.issn,identity.eissn) THEN 'issn'
                           WHEN metadata.eissn IS NOT NULL
                            AND metadata.eissn IN (identity.issn,identity.eissn) THEN 'eissn'
                           ELSE 'title' END AS match_basis
                    FROM smartlib.knowledge_object publication
                    JOIN smartlib.publication_metadata metadata
                      ON metadata.publication_id=publication.object_id
                    JOIN smartlib.relation_assertion published_in
                      ON published_in.subject_id=publication.object_id
                     AND published_in.predicate='publication.published_in'
                     AND smartlib.analysis_state_eligible(published_in.review_state)
                     AND published_in.system_to='infinity'::timestamptz
                    JOIN smartlib.journal_identity identity
                      ON identity.knowledge_object_id=published_in.object_id
                    JOIN smartlib.journal_metric_record record
                      ON record.journal_id=identity.journal_id
                    JOIN smartlib.journal_metric_release release
                      ON release.release_id=record.release_id
                   WHERE publication.object_type='publication'
                     AND smartlib.analysis_state_eligible(publication.review_state)
                     AND publication.system_to='infinity'::timestamptz
                     AND smartlib.journal_metric_analysis_eligible(release.release_id)
                     AND release.metric_year=metadata.publication_year
                   ORDER BY publication.object_id,release.metric_system,record.record_id"""
    ).fetchall()
    systems = {"jcr": 0, "cas_partition": 0}
    for row in rows:
        systems[str(row["metric_system"])] += 1
        if not apply:
            continue
        connection.execute(
            """INSERT INTO smartlib.publication_journal_metric_match
                      (publication_id,record_id,match_basis,match_state,confidence,year_policy,
                       decision_reason,decided_by,decided_at,created_by)
                 VALUES (%s,%s,%s,'matched',1,'publication_year',%s,%s,clock_timestamp(),%s)
                 ON CONFLICT (publication_id,record_id) DO UPDATE SET
                   match_basis=excluded.match_basis,match_state='matched',confidence=1,
                   year_policy='publication_year',decision_reason=excluded.decision_reason,
                   decided_by=excluded.decided_by,decided_at=excluded.decided_at""",
            (
                row["publication_id"], row["record_id"], row["match_basis"],
                "期刊对象一致，且指标年份与论文发表年份完全一致。",  # noqa: RUF001
                actor_id, actor_id,
            ),
        )
    if apply:
        connection.commit()
    else:
        connection.rollback()
    return {"candidates": len(rows), "jcr_records": systems["jcr"],
            "cas_partition_records": systems["cas_partition"], "applied": int(apply)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    actor_id = UUID(os.environ.get("SMARTLIB_DEV_ACTOR_ID", "00000000-0000-4000-8000-000000000001"))
    with psycopg.connect(os.environ["SMARTLIB_DATABASE_URL"], row_factory=dict_row) as connection:
        connection.execute("SELECT set_config('smartlib.actor_id', %s, false)", (str(actor_id),))
        print(match_metrics(connection, actor_id, apply=args.apply))


if __name__ == "__main__":
    main()
