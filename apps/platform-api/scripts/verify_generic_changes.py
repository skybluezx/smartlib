"""Exercise the shared workflow on a disposable database; all changes roll back."""

import os
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from smartlib_platform.changes import service as s
from smartlib_platform.publications.incremental import (
    decide_publication_supplement,
    list_publication_fulltexts,
    list_publication_supplements,
    submit_publication_supplement,
)
from smartlib_platform.publications.models import (
    PublicationSupplementCreate,
    PublicationSupplementDecisionCommand,
)

db = os.environ["SMARTLIB_TEST_DATABASE"]
assert db.endswith("_test")
actor = UUID(os.environ["SMARTLIB_DEV_ACTOR_ID"])
with psycopg.connect(os.environ["SMARTLIB_DATABASE_URL"], dbname=db, row_factory=dict_row) as c:
    try:
        c.execute("SELECT set_config('smartlib.actor_id',%s,true)", (str(actor),))
        people = c.execute(
            """SELECT object_id,object_type,description,attributes,version
                 FROM smartlib.knowledge_object
                 WHERE object_type='person'
                 AND system_to='infinity' ORDER BY object_id LIMIT 2"""
        ).fetchall()
        person, other = people
        relation = c.execute(
            """SELECT relation_id,predicate,confidence,attributes,version
                 FROM smartlib.relation_assertion
                 WHERE predicate='person.leads_project' LIMIT 1"""
        ).fetchone()

        def submit(items):
            return s.submit(
                c,
                s.SubmissionInput(
                    context_object_id=person["object_id"],
                    source_label="Integration evidence",
                    reason="Integration review",
                    proposals=items,
                ),
                actor,
                "test",
            )

        def proposal(row, field, value, kind="object"):
            return s.ProposalInput(
                target_kind=kind,
                target_id=row["object_id"] if kind == "object" else row["relation_id"],
                field_path=field,
                proposed_value=value,
                base_version=row["version"],
            )

        d = submit(
            [
                proposal(person, "description", "Reviewed description"),
                proposal(other, "description", "Other reviewed"),
                proposal(relation, "confidence", 0.9, "relation"),
            ]
        )
        assert (
            c.execute(
                "SELECT description FROM smartlib.knowledge_object WHERE object_id=%s", (person["object_id"],)
            ).fetchone()["description"]
            == person["description"]
        )
        result = s.decide(
            c,
            d["submission_id"],
            s.DecisionInput(decision="accept", reason="Evidence checked"),
            actor,
            "test",
        )
        assert all(p["application_state"] == "applied" for p in result["proposals"])
        assert c.execute("SELECT count(*) n FROM smartlib.relation_evidence WHERE relation_id=%s AND evidence_id=%s",
                         (relation["relation_id"],d["evidence_id"])).fetchone()["n"] == 1
        from uuid import uuid4
        c.execute("SELECT set_config('smartlib.actor_id',%s,true)",(str(uuid4()),))
        try:
            s.get_submission(c,d["submission_id"])
        except LookupError:
            pass
        else:
            raise AssertionError("Unrelated actor can read restricted generic submission")
        c.execute("SELECT set_config('smartlib.actor_id',%s,true)",(str(actor),))
        version = c.execute(
            "SELECT version FROM smartlib.knowledge_object WHERE object_id=%s", (person["object_id"],)
        ).fetchone()["version"]
        s.decide(c, d["submission_id"], s.DecisionInput(decision="accept", reason="Repeat"), actor, "test")
        assert (
            c.execute(
                "SELECT version FROM smartlib.knowledge_object WHERE object_id=%s", (person["object_id"],)
            ).fetchone()["version"]
            == version
        )
        person = c.execute(
            """SELECT object_id,object_type,description,attributes,version
                 FROM smartlib.knowledge_object
                 WHERE object_id=%s""",
            (person["object_id"],),
        ).fetchone()
        d = submit([proposal(person, "description", "Must not overwrite")])
        c.execute(
            """UPDATE smartlib.knowledge_object
                 SET description=%s,version=version+1
                 WHERE object_id=%s""",
            ("Concurrent update", person["object_id"]),
        )
        result = s.decide(
            c, d["submission_id"], s.DecisionInput(decision="accept", reason="Stale"), actor, "test"
        )
        assert result["proposals"][0]["application_state"] == "conflict"
        assert (
            c.execute(
                "SELECT description FROM smartlib.knowledge_object WHERE object_id=%s", (person["object_id"],)
            ).fetchone()["description"]
            == "Concurrent update"
        )
        result = s.decide(
            c, d["submission_id"], s.DecisionInput(decision="reject", reason="Reject stale"), actor, "test"
        )
        assert result["proposals"][0]["application_state"] == "not_applicable"
        print(
            "PASS generic changes: multi-target, apply, repeat, conflict, reject"
        )
        pub = c.execute(
            """SELECT p.*
                 FROM smartlib.publication_metadata p
                 JOIN smartlib.knowledge_object o ON o.object_id=p.publication_id
                 WHERE o.system_to='infinity' LIMIT 1"""
        ).fetchone()
        pid = pub["publication_id"]
        assert isinstance(list_publication_supplements(c, pid), list)
        assert isinstance(list_publication_fulltexts(c, pid), list)
        command = PublicationSupplementCreate(
            source_kind="metadata",
            source_label="Integration supplement",
            metadata={"title": pub["title"] + " revised"},
        )
        submission = submit_publication_supplement(c, pid, command, actor, "test")
        result = decide_publication_supplement(
            c,
            submission.submission_id,
            PublicationSupplementDecisionCommand(
                decision="accept",
                reason="Checked evidence",
                proposal_ids=[p.proposal_id for p in submission.candidates],
            ),
            actor,
            "test",
        )
        assert result.status == "accepted" and result.candidates[0].application_state == "applied"
        newer = submit_publication_supplement(
            c,
            pid,
            PublicationSupplementCreate(
                source_kind="metadata", source_label="stale", metadata={"title": "Stale title"}
            ),
            actor,
            "test",
        )
        c.execute(
            """UPDATE smartlib.publication_metadata
                 SET metadata_version=metadata_version+1
                 WHERE publication_id=%s""",
            (pid,),
        )
        result = decide_publication_supplement(
            c,
            newer.submission_id,
            PublicationSupplementDecisionCommand(decision="accept", reason="Conflict check"),
            actor,
            "test",
        )
        assert result.candidates[0].application_state == "conflict"
        print(
            "PASS publication changes: history, shared model, domain apply, stale protection"
        )
    finally:
        c.rollback()
