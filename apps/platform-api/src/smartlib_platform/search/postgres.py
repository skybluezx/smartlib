from time import perf_counter
from typing import Literal

from smartlib_platform.foundation.database import DbConnection
from smartlib_platform.foundation.types import ObjectType

from .cursor import decode_offset_cursor, encode_offset_cursor
from .errors import SearchModeUnavailable
from .models import AdapterSearchResult, InternalSearchHit, SearchAccessContext, SearchCommand


class PostgresSearchAdapter:
    backend: Literal["postgres"] = "postgres"

    def __init__(self, connection: DbConnection) -> None:
        self.connection = connection

    def search(self, command: SearchCommand, access: SearchAccessContext) -> AdapterSearchResult:
        if command.retrieval_mode != "lexical":
            raise SearchModeUnavailable(
                "semantic and hybrid retrieval require an approved embedding baseline"
            )

        started = perf_counter()
        offset = decode_offset_cursor(command.cursor, self.backend)
        object_types = list(command.object_types) or None
        pattern = command.query_text.casefold()
        parameters = (
            command.query_text,
            pattern,
            access.actor_id,
            object_types,
            object_types,
            command.page_size + 1,
            offset,
        )
        rows = self.connection.execute(
            """WITH input AS (
                   SELECT websearch_to_tsquery('simple', %s) AS query
               ), ranked AS (
                   SELECT document.object_id, document.object_type, document.canonical_name,
                          document.description, document.visibility, document.created_by,
                          document.object_version, document.projection_version,
                          document.source_updated_at,
                          ts_rank_cd(document.search_vector, input.query, 32)
                          + CASE
                                WHEN lower(document.canonical_name) = %s THEN 4.0
                                WHEN strpos(lower(document.canonical_name), %s) > 0 THEN 2.0
                                ELSE 0.0
                            END AS score
                   FROM smartlib_projection.search_document AS document
                   CROSS JOIN input
                   WHERE (
                       document.search_vector @@ input.query
                       OR strpos(lower(document.canonical_name), %s) > 0
                       OR strpos(lower(COALESCE(document.description, '')), %s) > 0
                   )
                     AND (document.visibility = 'public' OR document.created_by = %s)
                     AND (%s::text[] IS NULL OR document.object_type = ANY(%s::text[]))
               )
               SELECT * FROM ranked
               ORDER BY score DESC, canonical_name, object_id
               LIMIT %s OFFSET %s""",
            (
                parameters[0],
                parameters[1],
                parameters[1],
                parameters[1],
                parameters[1],
                parameters[2],
                parameters[3],
                parameters[4],
                parameters[5],
                parameters[6],
            ),
        ).fetchall()

        has_more = len(rows) > command.page_size
        page_rows = rows[: command.page_size]
        facets = self._facets(command, access, object_types, pattern)
        hits = tuple(
            InternalSearchHit(
                object_id=row["object_id"],
                object_type=row["object_type"],
                canonical_name=row["canonical_name"],
                description=row["description"],
                visibility=row["visibility"],
                created_by=row["created_by"],
                score=float(row["score"]),
                recall_channels=("lexical",),
                object_version=row["object_version"],
                projection_version=row["projection_version"],
                source_updated_at=row["source_updated_at"],
            )
            for row in page_rows
        )
        return AdapterSearchResult(
            hits=hits,
            object_type_facets=facets,
            next_cursor=(
                encode_offset_cursor(self.backend, offset + command.page_size) if has_more else None
            ),
            backend=self.backend,
            took_ms=(perf_counter() - started) * 1000,
            warnings=("PostgreSQL simple analyzer is a POC baseline, not accepted Chinese relevance.",),
        )

    def _facets(
        self,
        command: SearchCommand,
        access: SearchAccessContext,
        object_types: list[ObjectType] | None,
        pattern: str,
    ) -> dict[str, int]:
        rows = self.connection.execute(
            """WITH input AS (
                   SELECT websearch_to_tsquery('simple', %s) AS query
               )
               SELECT document.object_type, count(*) AS result_count
               FROM smartlib_projection.search_document AS document
               CROSS JOIN input
               WHERE (
                   document.search_vector @@ input.query
                   OR strpos(lower(document.canonical_name), %s) > 0
                   OR strpos(lower(COALESCE(document.description, '')), %s) > 0
               )
                 AND (document.visibility = 'public' OR document.created_by = %s)
                 AND (%s::text[] IS NULL OR document.object_type = ANY(%s::text[]))
               GROUP BY document.object_type
               ORDER BY document.object_type""",
            (command.query_text, pattern, pattern, access.actor_id, object_types, object_types),
        ).fetchall()
        return {row["object_type"]: row["result_count"] for row in rows}
