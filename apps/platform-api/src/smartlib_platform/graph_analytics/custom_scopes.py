from hashlib import sha256
from uuid import UUID

from psycopg import IntegrityError

from smartlib_platform.foundation.database import DbConnection
from smartlib_platform.graph.hugegraph import HugeGraphAdapter
from smartlib_platform.graph.models import GraphAccessContext

from .models import (
    CustomGraphScopeCreate,
    CustomGraphScopeJournal,
    CustomGraphScopePreview,
    CustomGraphScopePublication,
    SavedCustomGraphScope,
)


class CustomScopeNameConflictError(ValueError):
    pass


def execute_custom_scope(
    connection: DbConnection,
    adapter: HugeGraphAdapter,
    graph_query: str,
    access: GraphAccessContext,
) -> tuple[list[UUID], CustomGraphScopePreview]:
    publication_ids, truncated, took_ms = adapter.custom_publication_scope(graph_query, access)
    eligible_ids = _eligible_publication_ids(connection, publication_ids)
    preview = _scope_preview(connection, eligible_ids, graph_query, truncated, took_ms)
    return eligible_ids, preview


def _eligible_publication_ids(connection: DbConnection, publication_ids: list[UUID]) -> list[UUID]:
    if not publication_ids:
        return []
    rows = connection.execute(
        """SELECT object_id
             FROM smartlib.knowledge_object
            WHERE object_id=ANY(%s::uuid[])
              AND object_type='publication'
              AND system_to='infinity'::timestamptz
              AND smartlib.analysis_state_eligible(review_state)
            ORDER BY object_id""",
        (publication_ids,),
    ).fetchall()
    return [row["object_id"] for row in rows]


def _scope_preview(
    connection: DbConnection,
    publication_ids: list[UUID],
    graph_query: str,
    truncated: bool,
    took_ms: float,
) -> CustomGraphScopePreview:
    summary = connection.execute(
        """SELECT count(*)::integer AS publication_count,
                  min(metadata.publication_year)::integer AS minimum_year,
                  max(metadata.publication_year)::integer AS maximum_year,
                  count(*) FILTER (WHERE EXISTS (
                      SELECT 1 FROM smartlib.analysis_relation authorship
                       WHERE authorship.object_id=publication.object_id
                         AND authorship.predicate='person.authored'
                         AND authorship.system_to='infinity'::timestamptz
                         AND smartlib.analysis_state_eligible(authorship.review_state)
                  ))::integer AS publications_with_authors,
                  count(*) FILTER (WHERE EXISTS (
                      SELECT 1 FROM smartlib.analysis_relation affiliation
                       WHERE coalesce(affiliation.context_object_id::text,
                                       affiliation.attributes->>'publication_id')=publication.object_id::text
                         AND affiliation.predicate='person.affiliated_with'
                         AND affiliation.system_to='infinity'::timestamptz
                         AND smartlib.analysis_state_eligible(affiliation.review_state)
                  ))::integer AS publications_with_affiliations
             FROM smartlib.knowledge_object publication
             LEFT JOIN smartlib.publication_metadata metadata
               ON metadata.publication_id=publication.object_id
            WHERE publication.object_id=ANY(%s::uuid[])""",
        (publication_ids,),
    ).fetchone()
    journal_rows = connection.execute(
        """SELECT journal.object_id::text, journal.canonical_name AS name,
                  count(DISTINCT relation.subject_id)::integer AS publication_count
             FROM smartlib.analysis_relation relation
             JOIN smartlib.knowledge_object journal ON journal.object_id=relation.object_id
            WHERE relation.subject_id=ANY(%s::uuid[])
              AND relation.predicate='publication.published_in'
              AND relation.system_to='infinity'::timestamptz
              AND smartlib.analysis_state_eligible(relation.review_state)
              AND journal.system_to='infinity'::timestamptz
              AND smartlib.analysis_state_eligible(journal.review_state)
            GROUP BY journal.object_id,journal.canonical_name
            ORDER BY publication_count DESC,journal.canonical_name
            LIMIT 5""",
        (publication_ids,),
    ).fetchall()
    sample_rows = connection.execute(
        """SELECT publication.object_id,publication.canonical_name AS title,
                  metadata.publication_year,journal.canonical_name AS journal_name
             FROM smartlib.knowledge_object publication
             LEFT JOIN smartlib.publication_metadata metadata
               ON metadata.publication_id=publication.object_id
             LEFT JOIN smartlib.analysis_relation published
               ON published.subject_id=publication.object_id
              AND published.predicate='publication.published_in'
              AND published.system_to='infinity'::timestamptz
              AND smartlib.analysis_state_eligible(published.review_state)
             LEFT JOIN smartlib.knowledge_object journal
               ON journal.object_id=published.object_id
              AND journal.system_to='infinity'::timestamptz
              AND smartlib.analysis_state_eligible(journal.review_state)
            WHERE publication.object_id=ANY(%s::uuid[])
            ORDER BY metadata.publication_year DESC NULLS LAST,publication.canonical_name
            LIMIT 8""",
        (publication_ids,),
    ).fetchall()
    summary = summary or {}
    return CustomGraphScopePreview(
        query_hash=sha256(graph_query.strip().encode()).hexdigest(),
        publication_count=summary.get("publication_count", 0),
        publications_with_authors=summary.get("publications_with_authors", 0),
        publications_with_affiliations=summary.get("publications_with_affiliations", 0),
        minimum_year=summary.get("minimum_year"),
        maximum_year=summary.get("maximum_year"),
        top_journals=[CustomGraphScopeJournal.model_validate(row) for row in journal_rows],
        sample_publications=[CustomGraphScopePublication.model_validate(row) for row in sample_rows],
        truncated=truncated,
        took_ms=took_ms,
    )


def list_custom_scopes(connection: DbConnection) -> list[SavedCustomGraphScope]:
    rows = connection.execute(
        """SELECT scope_id,name,description,query_language,graph_query,last_result_count,
                  last_executed_at,created_at,updated_at
             FROM smartlib.custom_graph_analysis_scope
            ORDER BY updated_at DESC,name"""
    ).fetchall()
    return [SavedCustomGraphScope.model_validate(row) for row in rows]


def get_custom_scope(connection: DbConnection, scope_id: UUID) -> SavedCustomGraphScope | None:
    row = connection.execute(
        """SELECT scope_id,name,description,query_language,graph_query,last_result_count,
                  last_executed_at,created_at,updated_at
             FROM smartlib.custom_graph_analysis_scope WHERE scope_id=%s""",
        (scope_id,),
    ).fetchone()
    return SavedCustomGraphScope.model_validate(row) if row else None


def create_custom_scope(
    connection: DbConnection,
    command: CustomGraphScopeCreate,
    actor_id: UUID,
    preview: CustomGraphScopePreview,
) -> SavedCustomGraphScope:
    try:
        row = connection.execute(
            """INSERT INTO smartlib.custom_graph_analysis_scope
                      (name,description,graph_query,last_result_count,last_executed_at,created_by)
               VALUES(btrim(%s),nullif(btrim(%s),''),%s,%s,clock_timestamp(),%s)
            RETURNING scope_id,name,description,query_language,graph_query,last_result_count,
                      last_executed_at,created_at,updated_at""",
            (
                command.name,
                command.description or "",
                command.graph_query.strip(),
                preview.publication_count,
                actor_id,
            ),
        ).fetchone()
    except IntegrityError as exc:
        raise CustomScopeNameConflictError("已存在同名的自定义范围") from exc
    assert row is not None
    return SavedCustomGraphScope.model_validate(row)


def mark_custom_scope_executed(
    connection: DbConnection, scope_id: UUID, publication_count: int
) -> None:
    connection.execute(
        """UPDATE smartlib.custom_graph_analysis_scope
              SET last_result_count=%s,last_executed_at=clock_timestamp()
            WHERE scope_id=%s""",
        (publication_count, scope_id),
    )


def delete_custom_scope(connection: DbConnection, scope_id: UUID) -> bool:
    return connection.execute(
        "DELETE FROM smartlib.custom_graph_analysis_scope WHERE scope_id=%s RETURNING scope_id",
        (scope_id,),
    ).fetchone() is not None
