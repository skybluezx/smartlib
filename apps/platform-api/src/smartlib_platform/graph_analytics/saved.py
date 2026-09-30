"""Owner-scoped definitions and server-computed immutable analytical snapshots."""
import json
from hashlib import sha256
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from smartlib_platform.foundation.database import DbConnection

from .models import AnalysisSaveCommand, SavedAnalysis, SavedAnalysisDetail, ScholarGraphAnalytics


def _uuid_values(value: Any) -> set[UUID]:
    if isinstance(value, dict):
        return set().union(*(_uuid_values(v) for v in value.values()))
    if isinstance(value, list):
        return set().union(*(_uuid_values(v) for v in value))
    if isinstance(value, str):
        try:
            return {UUID(value)}
        except ValueError:
            pass
    return set()


def save_analysis(connection: DbConnection, command: AnalysisSaveCommand,
                  actor_id: UUID, result: ScholarGraphAnalytics | None) -> SavedAnalysis:
    payload = result.model_dump(mode='json') if result else None
    objects = connection.execute("""SELECT object_id,version FROM smartlib.knowledge_object
        WHERE object_id=ANY(%s::uuid[]) ORDER BY object_id""",
        (list(_uuid_values(payload)),)).fetchall() if result else []
    outcome = result.collaboration_outcomes if result else None
    pids = [p.publication_id for p in outcome.papers] if outcome else []
    relations = connection.execute("""SELECT relation_id,version,review_state
        FROM smartlib.relation_assertion WHERE system_to='infinity'
        AND (subject_id=ANY(%s::uuid[]) OR object_id=ANY(%s::uuid[])
             OR context_object_id=ANY(%s::uuid[])) ORDER BY relation_id""",
        (pids, pids, pids)).fetchall() if pids else []
    row = connection.execute("""INSERT INTO smartlib.saved_analysis
        (name,kind,definition,result,result_hash,publication_count,object_ids,metric_release_ids,
         provenance,created_by)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""", (
        command.name.strip(), command.kind, Jsonb(command.definition.model_dump(mode='json')),
        Jsonb(payload) if payload else None,
        sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        if payload else None,
        result.scope.publication_count if result else None,
        [o['object_id'] for o in objects],
        [outcome.metric_release_id] if outcome and outcome.metric_release_id else [],
        Jsonb(json.loads(json.dumps({
            'definition_version': command.definition.definition_version,
            'calculation_version': outcome.definition_version if outcome else None,
            'data_version': result.data_version if result else None,
            'analysis_policy': 'pending+approved; rejected+superseded excluded',
            'publication_ids': pids, 'object_versions': objects, 'relation_versions': relations,
            'source': 'server_computed_repeatable_read',
        }, default=str))), actor_id,
    )).fetchone()
    assert row is not None
    return SavedAnalysis.model_validate(row)


def list_analyses(connection: DbConnection) -> list[SavedAnalysis]:
    return [SavedAnalysis.model_validate(row) for row in connection.execute("""
        SELECT analysis_id,name,kind,definition,created_at,publication_count,result_hash
        FROM smartlib.saved_analysis ORDER BY created_at DESC LIMIT 100""").fetchall()]


def get_analysis(connection: DbConnection, analysis_id: UUID) -> SavedAnalysisDetail | None:
    row = connection.execute('SELECT * FROM smartlib.saved_analysis WHERE analysis_id=%s',
                             (analysis_id,)).fetchone()
    return SavedAnalysisDetail.model_validate(row) if row else None
