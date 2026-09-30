"""Local acceptance check. All fixture data is rolled back, including audit/projections."""

import os

import psycopg
from psycopg.rows import dict_row

from smartlib_platform.scholars.service import get_scholar_profile, list_scholars


def main():
    with psycopg.connect(os.environ["SMARTLIB_DATABASE_URL"], row_factory=dict_row) as conn:
        try:
            actor = os.environ["SMARTLIB_DEV_ACTOR_ID"]
            conn.execute("SELECT set_config('smartlib.actor_id', %s, true)", (actor,))
            person = conn.execute(
                "SELECT object_id FROM smartlib.knowledge_object WHERE object_type='person' LIMIT 1"
            ).fetchone()["object_id"]
            org = conn.execute(
                """INSERT INTO smartlib.knowledge_object
              (object_type,canonical_name,attributes,created_by) VALUES
              ('organization','__affiliation_acceptance__',
               '{"source":"acceptance","identity_resolution_status":"confirmed"}',%s)
              RETURNING object_id""",
                (actor,),
            ).fetchone()["object_id"]
            source = conn.execute("""INSERT INTO smartlib.source_system
              (code,name,owner_department,source_type,authorization_state,personnel_authority)
              VALUES ('affiliation_acceptance','Acceptance only','test','database','approved',true)
              RETURNING source_system_id""").fetchone()["source_system_id"]
            ref = conn.execute(
                """INSERT INTO smartlib.source_reference
              (object_id,source_system_id,external_id) VALUES (%s,%s,'acceptance')
              RETURNING source_reference_id""",
                (person, source),
            ).fetchone()["source_reference_id"]
            evidence = conn.execute(
                """INSERT INTO smartlib.evidence_record
              (object_id,source_reference_id,evidence_type,citation,verification_state,created_by)
              VALUES (%s,%s,'business_record','Acceptance only','confirmed',%s)
              RETURNING evidence_id""",
                (person, ref, actor),
            ).fetchone()["evidence_id"]
            relation = conn.execute(
                """INSERT INTO smartlib.relation_assertion
              (subject_id,predicate,object_id,fact_class,review_state,created_by)
              VALUES (%s,'person.authoritatively_affiliated_with',%s,'business_fact','approved',%s)
              RETURNING relation_id""",
                (person, org, actor),
            ).fetchone()["relation_id"]
            conn.execute("INSERT INTO smartlib.relation_evidence VALUES (%s,%s,now())", (relation, evidence))
            conn.execute("SET CONSTRAINTS ALL IMMEDIATE")
            profile = get_scholar_profile(conn, person)
            assert any(
                a.relation_id == relation and a.category == "authoritative" for a in profile.affiliations
            )
            assert (
                "__affiliation_acceptance__"
                in list_scholars(conn, object_id=person)[0].authoritative_organizations
            )
            for sql, params in [
                ("DELETE FROM smartlib.relation_evidence WHERE relation_id=%s", (relation,)),
                (
                    "UPDATE smartlib.source_system SET personnel_authority=false WHERE source_system_id=%s",
                    (source,),
                ),
                (
                    "UPDATE smartlib.evidence_record SET verification_state='needs_review' WHERE evidence_id=%s",
                    (evidence,),
                ),
            ]:
                try:
                    with conn.transaction():
                        conn.execute(sql, params)
                except psycopg.errors.CheckViolation, psycopg.errors.InsufficientPrivilege:
                    pass
                else:
                    raise AssertionError("Invalid personnel evidence was accepted")
            conn.execute(
                "UPDATE smartlib.relation_assertion SET valid_to='2000-01-01' WHERE relation_id=%s",
                (relation,),
            )
            assert (
                "__affiliation_acceptance__"
                not in list_scholars(conn, object_id=person)[0].authoritative_organizations
            )
            assert any(
                not a.is_current
                for a in get_scholar_profile(conn, person).affiliations
                if a.relation_id == relation
            )
            print(
                "PASS: classification, current/history, evidence deletion, source demotion, evidence rejection"
            )
        finally:
            conn.rollback()
            print("All acceptance fixture data rolled back")


if __name__ == "__main__":
    main()
