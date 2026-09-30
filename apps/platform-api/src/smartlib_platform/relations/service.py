from uuid import UUID

from psycopg.types.json import Jsonb

from smartlib_platform.foundation.database import DbConnection

from .models import EvidenceCreate, EvidenceView, RelationCreate, RelationView

_RELATION_COLUMNS = """relation_id, subject_id, predicate, object_id, context_object_id,
fact_class, confidence, visibility, license_tags, review_state,
model_version, attributes, version, created_by, created_at, updated_at"""


def create_evidence(
    connection: DbConnection, object_id: UUID, command: EvidenceCreate, actor_id: UUID
) -> EvidenceView:
    row = connection.execute(
        """INSERT INTO smartlib.evidence_record
                  (object_id, evidence_type, evidence_kind, fulltext_resource_id, page_number,
                   evidence_locator, verification_state, citation, excerpt, visibility,
                   license_tags, metadata, created_by)
             SELECT object_id, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
             FROM smartlib.knowledge_object WHERE object_id = %s
             RETURNING evidence_id, object_id, evidence_type, evidence_kind,
                       fulltext_resource_id, page_number, evidence_locator, verification_state,
                       citation, excerpt, visibility, license_tags, metadata, created_by, created_at""",
        (
            command.evidence_type,
            command.evidence_kind,
            command.fulltext_resource_id,
            command.page_number,
            Jsonb(command.evidence_locator),
            command.verification_state,
            command.citation,
            command.excerpt,
            command.visibility,
            command.license_tags,
            Jsonb(command.metadata),
            actor_id,
            object_id,
        ),
    ).fetchone()
    if row is None:
        raise LookupError("knowledge object not found")
    return EvidenceView.model_validate(row)


def create_relation(
    connection: DbConnection,
    command: RelationCreate,
    actor_id: UUID,
    trace_id: str,
) -> RelationView:
    visible_endpoints = connection.execute(
        "SELECT count(*) AS count FROM smartlib.knowledge_object WHERE object_id = ANY(%s)",
        ([command.subject_id, command.object_id],),
    ).fetchone()
    expected_endpoint_count = 1 if command.subject_id == command.object_id else 2
    if visible_endpoints is None or visible_endpoints["count"] != expected_endpoint_count:
        raise LookupError("relation endpoint not found")

    row = connection.execute(
        f"""INSERT INTO smartlib.relation_assertion
                  (subject_id, predicate, object_id, context_object_id,
                   fact_class, confidence, visibility,
                   license_tags, review_state, model_version, attributes, created_by)
             VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
             RETURNING {_RELATION_COLUMNS}""",
        (
            command.subject_id,
            command.predicate,
            command.object_id,
            command.context_object_id,
            command.fact_class,
            command.confidence,
            command.visibility,
            command.license_tags,
            command.review_state,
            command.model_version,
            Jsonb(command.attributes),
            actor_id,
        ),
    ).fetchone()
    if row is None:
        raise RuntimeError("relation insert returned no row")

    if command.evidence_ids:
        inserted = connection.execute(
            """INSERT INTO smartlib.relation_evidence (relation_id, evidence_id)
               SELECT %s, evidence_id FROM smartlib.evidence_record WHERE evidence_id = ANY(%s)
               ON CONFLICT DO NOTHING""",
            (row["relation_id"], command.evidence_ids),
        ).rowcount
        if inserted != len(set(command.evidence_ids)):
            raise LookupError("one or more evidence records are unavailable")

    connection.execute(
        """INSERT INTO smartlib.outbox_event
                  (aggregate_type, aggregate_id, event_type, event_version, payload, trace_id)
             VALUES ('relation_assertion', %s, 'knowledge.relation.created', 1, %s, %s)""",
        (
            row["relation_id"],
            Jsonb({"relation_id": str(row["relation_id"]), "version": row["version"]}),
            trace_id,
        ),
    )
    return RelationView.model_validate({**row, "evidence_ids": command.evidence_ids})
