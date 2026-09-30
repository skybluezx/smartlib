"""Integration check against an explicitly named disposable database; always rolls back."""

import os
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row

from smartlib_platform.graph_analytics.service import get_scholar_graph_analytics
from smartlib_platform.publications.incremental import _apply_funding_relation


def main():
    database = os.environ["SMARTLIB_TEST_DATABASE"]
    if not database.endswith("_test"):
        raise ValueError("Disposable test database required")
    actor = UUID(os.environ["SMARTLIB_DEV_ACTOR_ID"])
    with psycopg.connect(
        os.environ["SMARTLIB_DATABASE_URL"], dbname=database, row_factory=dict_row
    ) as connection:
        try:
            connection.execute("""SELECT set_config('smartlib.actor_id',%s,true)""", (str(actor),))
            publication = connection.execute("""SELECT object_id
                    FROM smartlib.knowledge_object
                    WHERE object_type='publication'
                    AND system_to='infinity' LIMIT 1""").fetchone()["object_id"]
            evidence = uuid4()
            connection.execute(
                """INSERT INTO smartlib.evidence_record
                    (evidence_id,object_id,evidence_type,citation,created_by)
                    VALUES(%s,%s,'business_record','funding integration test',%s)""",
                (evidence, publication, actor),
            )
            before = get_scholar_graph_analytics(connection, graph_backend="postgresql").model_dump()
            for grant, expected_type, expected_predicate in [
                ("TEST-2026-001", "project", "publication.supported_by_project"),
            ]:
                value = {
                    "funder_name": "Integration Test Foundation",
                    "grant_id": grant,
                    "country": None,
                    "metadata": {},
                }
                for _ in range(2):
                    _apply_funding_relation(
                        connection, publication, evidence, value, actor, "predicate-refactor-test"
                    )
                rows = connection.execute(
                    """SELECT r.relation_id,r.predicate,o.object_type
                    FROM smartlib.relation_assertion r
                    JOIN smartlib.knowledge_object o ON o.object_id=r.object_id
                    WHERE r.subject_id=%s
                    AND o.canonical_name=%s
                    AND r.predicate=%s""",
                    (publication, grant or value["funder_name"], expected_predicate),
                ).fetchall()
                assert len(rows) == 1 and rows[0]["object_type"] == expected_type, rows
                assert (
                    connection.execute(
                        """SELECT count(*) n FROM smartlib.relation_evidence
                    WHERE relation_id=%s AND evidence_id=%s""",
                        (rows[0]["relation_id"], evidence),
                    ).fetchone()["n"]
                    == 1
                )
                print(
                    f"PASS {expected_type}: canonical predicate, evidence, repeat submission"
                )
            _apply_funding_relation(connection, publication, evidence,
                {"funder_name": "Unresolved Test Foundation"}, actor, "funding-source-test")
            clue = connection.execute("SELECT attributes->'funding_source_clues' clues FROM smartlib.knowledge_object WHERE object_id=%s", (publication,)).fetchone()
            assert next(iter(clue["clues"].values()))["match_state"] == "project_unresolved"
            get_scholar_graph_analytics(connection, graph_backend="postgresql")
            assert before is not None
            for old in ["publication.funded_by", "funding_organization.part_of", "publication.acknowledges_funder"]:
                try:
                    with connection.transaction():
                        connection.execute(
                            """INSERT INTO smartlib.relation_assertion
                            (relation_id,subject_id,predicate,object_id,fact_class,created_by)
                            VALUES(%s,%s,%s,%s,'human_confirmed',%s)""",
                            (uuid4(), publication, old, publication, actor),
                        )
                except psycopg.errors.CheckViolation, psycopg.errors.ForeignKeyViolation:
                    pass
                else:
                    raise AssertionError(f"Obsolete predicate accepted: {old}")
            print("PASS analytics query and obsolete predicate rejection")
        finally:
            connection.rollback()


if __name__ == "__main__":
    main()
