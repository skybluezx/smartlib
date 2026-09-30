"""Reviewed changes with explicit targets, evidence, and optimistic concurrency."""

from typing import Any, Literal
from uuid import UUID, uuid4

from psycopg import sql
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from smartlib_platform.identities import service as identities


class ProposalInput(BaseModel):
    target_kind: Literal["object", "relation"]
    target_id: UUID
    field_path: str = Field(
        pattern=r"^(canonical_name|description|confidence|attributes\.[a-z][a-z0-9_]{0,99}|profile\.[a-z_]+|identifiers\.(orcid|ror)|identity\.aliases)$"
    )
    proposed_value: Any
    base_version: int = Field(ge=1)


class SubmissionInput(BaseModel):
    context_object_id: UUID
    source_label: str = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=1, max_length=2000)
    source_uri: str | None = None
    proposals: list[ProposalInput] = Field(min_length=1, max_length=100)


class DecisionInput(BaseModel):
    decision: Literal["accept", "reject"]
    reason: str = Field(min_length=1, max_length=2000)


def _target(c, kind, target_id):
    table, key = (
        ("knowledge_object", "object_id") if kind == "object" else ("relation_assertion", "relation_id")
    )
    row = c.execute(
        sql.SQL("SELECT {} FROM smartlib.{} WHERE {}=%s AND system_to='infinity' FOR UPDATE").format(
            sql.SQL(
                "object_id,object_type,canonical_name,description,attributes,version"
                if kind == "object"
                else "relation_id,predicate,confidence::float8 AS confidence,attributes,version"
            ),
            sql.Identifier(table),
            sql.Identifier(key),
        ),
        (target_id,),
    ).fetchone()
    if not row:
        raise LookupError("Change target is unavailable")
    if kind == "object" and row["object_type"] in identities.IDENTITY_TYPES:
        row["identity"] = identities.get_identity(c, target_id)
    return row, table, key


def _value(row, path):
    if path.startswith(("profile.", "identifiers.", "identity.")):
        return identities.current_value(row["identity"], path)
    return row.get("attributes", {}).get(path[11:]) if path.startswith("attributes.") else row.get(path)


def _validate(c, kind, row, path, value):
    if path.startswith(("profile.", "identifiers.", "identity.")):
        if kind != "object":
            raise ValueError("Identity fields require an object target")
        identities.normalize(c, row["object_type"], path, value)
        return
    if kind == "object" and row["object_type"] in {"publication", "journal"}:
        raise ValueError("Use the domain workflow for publication and journal changes")
    if path == "attributes.record_kind":
        raise ValueError("Object subtype changes require a domain migration")
    if path.startswith("attributes."):
        attributes = {**row["attributes"], path[11:]: value}
        c.execute(
            "SELECT smartlib.validate_registered_attributes(%s,%s,%s,%s)",
            (
                kind,
                row["object_type"] if kind == "object" else row["predicate"],
                str(attributes.get("record_kind", "*")),
                Jsonb(attributes),
            ),
        )
    elif kind == "object" and path in {"canonical_name", "description"}:
        if row["object_type"] in {"publication", "journal"}:
            raise ValueError("Publication and journal names require their domain workflow")
        if value is not None and not isinstance(value, str):
            raise ValueError("Text field requires a string")
        if path == "canonical_name" and (not isinstance(value, str) or not value.strip()):
            raise ValueError("Canonical name cannot be empty")
    elif kind == "relation" and path == "confidence":
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
            raise ValueError("Confidence must be between zero and one")
    else:
        raise ValueError("Unsupported target field")


def get_submission(c, submission_id):
    row = c.execute(
        "SELECT * FROM smartlib.change_submission WHERE submission_id=%s", (submission_id,)
    ).fetchone()
    if not row:
        raise LookupError("Change submission not found")
    proposals = c.execute(
        """SELECT *
                 FROM smartlib.change_proposal
                 WHERE submission_id=%s ORDER BY created_at,proposal_id""",
        (submission_id,),
    ).fetchall()
    return {**row, "proposals": proposals}


def _audit(c, actor, submission_id, action, trace, details):
    c.execute(
        """INSERT INTO audit.audit_event(actor_id,action,resource_type,resource_id,decision,trace_id,details)
                 VALUES(%s,%s,'change_submission',%s,'recorded',%s,%s)""",
        (actor, action, str(submission_id), trace, Jsonb(details)),
    )


def submit(c, command, actor, trace):
    c.execute("SELECT set_config('smartlib.change_reason',%s,true), set_config('smartlib.change_source',%s,true), set_config('smartlib.trace_id',%s,true)",
              (command.reason, command.source_label, str(trace)))
    context, _, _ = _target(c, "object", command.context_object_id)
    seen = set()
    prepared = []
    for item in sorted(command.proposals, key=lambda p: (p.target_kind, str(p.target_id), p.field_path)):
        identity = (item.target_kind, item.target_id, item.field_path)
        if identity in seen:
            raise ValueError("Duplicate target field in submission")
        seen.add(identity)
        row, _, _ = _target(c, item.target_kind, item.target_id)
        if row["version"] != item.base_version:
            raise ValueError("Target version changed; refresh before submitting")
        _validate(c, item.target_kind, row, item.field_path, item.proposed_value)
        prepared.append((item, _value(row, item.field_path)))
    sid, eid = uuid4(), uuid4()
    c.execute("SELECT set_config('smartlib.submission_id',%s,true)", (str(sid),))
    c.execute(
        """INSERT INTO smartlib.evidence_record(evidence_id,object_id,evidence_type,citation,excerpt,
                 metadata,created_by) VALUES(%s,%s,'business_record',%s,%s,%s,%s)""",
        (
            eid,
            command.context_object_id,
            command.source_label,
            command.reason,
            Jsonb({"source_uri": command.source_uri}),
            actor,
        ),
    )
    c.execute(
        """INSERT INTO smartlib.change_submission(submission_id,context_object_id,evidence_id,
                 source_kind,source_label,source_uri,payload,status,impact,base_version,workflow_key,created_by)
                 VALUES(%s,%s,%s,'manual',%s,%s,%s,'needs_review','corrective',%s,'entity',%s)""",
        (
            sid,
            command.context_object_id,
            eid,
            command.source_label,
            command.source_uri,
            Jsonb(command.model_dump(mode="json")),
            context["version"],
            actor,
        ),
    )
    for item, current in prepared:
        c.execute(
            """INSERT INTO smartlib.change_proposal(proposal_id,submission_id,target_object_id,
                     target_relation_id,base_version,field_path,current_value,proposed_value,
                     change_type,risk_level,status,created_by)
                     VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'replace','review','pending',%s)""",
            (
                uuid4(),
                sid,
                item.target_id if item.target_kind == "object" else None,
                item.target_id if item.target_kind == "relation" else None,
                item.base_version,
                item.field_path,
                Jsonb(current),
                Jsonb(item.proposed_value),
                actor,
            ),
        )
    _audit(c, actor, sid, "change.submitted", trace, {"proposal_count": len(prepared)})
    return get_submission(c, sid)


def decide(c, sid, command, actor, trace):
    c.execute("SELECT set_config('smartlib.change_reason',%s,true), set_config('smartlib.change_source','change.decision',true), set_config('smartlib.trace_id',%s,true), set_config('smartlib.submission_id',%s,true)",
              (command.reason, str(trace), str(sid)))
    c.execute(
        "SELECT submission_id FROM smartlib.change_submission WHERE submission_id=%s FOR UPDATE", (sid,)
    )
    submission = get_submission(c, sid)
    if submission["workflow_key"] != "entity":
        raise ValueError("Use the publication decision workflow for publication changes")
    if submission["status"] != "needs_review":
        return submission
    proposals = submission["proposals"]
    targets = {}
    if command.decision == "accept":
        # Lock all targets and check all versions before any write, including shared targets.
        for p in sorted(proposals, key=lambda p: str(p["target_object_id"] or p["target_relation_id"])):
            kind = "object" if p["target_object_id"] else "relation"
            tid = p["target_object_id"] or p["target_relation_id"]
            if (kind, tid) not in targets:
                targets[(kind, tid)] = _target(c, kind, tid)
            row, table, key = targets[(kind, tid)]
            if row["version"] != p["base_version"] or _value(row, p["field_path"]) != p["current_value"]:
                c.execute(
                    """UPDATE smartlib.change_proposal
                 SET application_state='conflict',decision_reason=%s
                 WHERE submission_id=%s""",
                    ("Target changed after submission; submit a refreshed proposal", sid),
                )
                _audit(c, actor, sid, "change.conflict", trace, {"reason": command.reason})
                return get_submission(c, sid)
            _validate(c, kind, row, p["field_path"], p["proposed_value"])
        grouped = {}
        for p in proposals:
            kind = "object" if p["target_object_id"] else "relation"
            tid = p["target_object_id"] or p["target_relation_id"]
            row, _, _ = targets[(kind, tid)]
            updates = grouped.setdefault((kind, tid), {})
            path, value = p["field_path"], p["proposed_value"]
            if path.startswith("attributes."):
                updates.setdefault("attributes", dict(row["attributes"]))[path[11:]] = value
            else:
                updates[path] = value
        for (kind, tid), updates in grouped.items():
            _row, table, key = targets[(kind, tid)]
            identity_updates = {
                k: v for k, v in updates.items() if k.startswith(("profile.", "identifiers.", "identity."))
            }
            if identity_updates:
                identities.apply(c, _row, identity_updates, submission, actor)
            updates = {k: v for k, v in updates.items() if k not in identity_updates}
            assignments = [sql.SQL("{}=%s").format(sql.Identifier(field)) for field in updates]
            assignments.append(sql.SQL("version=version+1"))
            values = [Jsonb(value) if field == "attributes" else value for field, value in updates.items()]
            updated = c.execute(
                sql.SQL("UPDATE smartlib.{} SET {} WHERE {}=%s RETURNING version").format(
                    sql.Identifier(table), sql.SQL(",").join(assignments), sql.Identifier(key)
                ),
                (*values, tid),
            ).fetchone()
            if updated is None:
                raise ValueError("Target write permission changed")
            c.execute(
                """INSERT INTO smartlib.outbox_event(event_id,aggregate_type,aggregate_id,event_type,
                         event_version,payload,trace_id) VALUES(%s,%s,%s,%s,%s,%s,%s)""",
                (
                    uuid4(),
                    table,
                    tid,
                    "knowledge.object.updated" if kind == "object" else "knowledge.relation.updated",
                    updated["version"],
                    Jsonb({key: str(tid), "version": updated["version"]}),
                    trace,
                ),
            )
            if kind == "relation":
                c.execute(
                    """INSERT INTO smartlib.relation_evidence(relation_id,evidence_id) VALUES(%s,%s)
                 ON CONFLICT DO NOTHING""",
                    (tid, submission["evidence_id"]),
                )
    accepted = command.decision == "accept"
    c.execute(
        """UPDATE smartlib.change_proposal
                 SET status=%s,application_state=%s,
                 applied_at=CASE WHEN %s THEN clock_timestamp() ELSE NULL END,
                 decision_reason=%s,decided_by=%s,decided_at=clock_timestamp()
                 WHERE submission_id=%s""",
        (
            "accepted" if accepted else "rejected",
            "applied" if accepted else "not_applicable",
            accepted,
            command.reason,
            actor,
            sid,
        ),
    )
    c.execute(
        """UPDATE smartlib.change_submission
                 SET status=%s,decision_reason=%s,decided_by=%s,
                 decided_at=clock_timestamp()
                 WHERE submission_id=%s""",
        ("accepted" if accepted else "rejected", command.reason, actor, sid),
    )
    _audit(c, actor, sid, "change.decided", trace, {"decision": command.decision, "reason": command.reason})
    return get_submission(c, sid)
