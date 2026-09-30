from .errors import SearchAuthorizationInvariantError
from .models import SearchAccessContext, SearchCommand, SearchFacets, SearchHit, SearchResult
from .ports import SearchPort


def search_knowledge(port: SearchPort, command: SearchCommand, access: SearchAccessContext) -> SearchResult:
    adapter_result = port.search(command, access)
    public_hits: list[SearchHit] = []

    for hit in adapter_result.hits:
        if hit.visibility != "public" and hit.created_by != access.actor_id:
            raise SearchAuthorizationInvariantError(
                "search adapter returned a document outside the trusted access scope"
            )
        public_hits.append(
            SearchHit(
                object_id=hit.object_id,
                object_type=hit.object_type,
                canonical_name=hit.canonical_name,
                description=hit.description,
                score=hit.score,
                recall_channels=list(hit.recall_channels),
                object_version=hit.object_version,
                projection_version=hit.projection_version,
                source_updated_at=hit.source_updated_at,
            )
        )

    return SearchResult(
        query_text=command.query_text,
        retrieval_mode=command.retrieval_mode,
        hits=public_hits,
        facets=SearchFacets(object_types=adapter_result.object_type_facets),
        next_cursor=adapter_result.next_cursor,
        backend=adapter_result.backend,
        took_ms=adapter_result.took_ms,
        warnings=list(adapter_result.warnings),
    )
