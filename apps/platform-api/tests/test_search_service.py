from datetime import UTC, datetime
from uuid import UUID

import pytest

from smartlib_platform.search.errors import SearchAuthorizationInvariantError
from smartlib_platform.search.models import (
    AdapterSearchResult,
    InternalSearchHit,
    SearchAccessContext,
    SearchCommand,
)
from smartlib_platform.search.service import search_knowledge

ACTOR_A = UUID("10000000-0000-0000-0000-000000000001")
ACTOR_B = UUID("10000000-0000-0000-0000-000000000002")


class FakeSearchPort:
    def __init__(self, hit: InternalSearchHit) -> None:
        self.hit = hit

    def search(self, command: SearchCommand, access: SearchAccessContext) -> AdapterSearchResult:
        return AdapterSearchResult(
            hits=(self.hit,),
            object_type_facets={"person": 1},
            next_cursor=None,
            backend="postgres",
            took_ms=1.0,
        )


def make_hit(*, visibility: str, created_by: UUID) -> InternalSearchHit:
    return InternalSearchHit(
        object_id=UUID("30000000-0000-0000-0000-000000000001"),
        object_type="person",
        canonical_name="授权检索测试",
        description="SmartLib search scope test",
        visibility=visibility,  # type: ignore[arg-type]
        created_by=created_by,
        score=1.0,
        recall_channels=("lexical",),
        object_version=1,
        projection_version="search-document-v1",
        source_updated_at=datetime.now(UTC),
    )


def access_for(actor_id: UUID) -> SearchAccessContext:
    return SearchAccessContext(actor_id=actor_id, purpose="interactive_search", trace_id="test")


def test_public_hit_is_returned_without_internal_access_fields() -> None:
    result = search_knowledge(
        FakeSearchPort(make_hit(visibility="public", created_by=ACTOR_B)),
        SearchCommand(query_text="授权检索"),
        access_for(ACTOR_A),
    )
    assert result.hits[0].canonical_name == "授权检索测试"
    assert "visibility" not in result.hits[0].model_dump()
    assert "created_by" not in result.hits[0].model_dump()


def test_owned_private_hit_is_returned() -> None:
    result = search_knowledge(
        FakeSearchPort(make_hit(visibility="private", created_by=ACTOR_A)),
        SearchCommand(query_text="授权检索"),
        access_for(ACTOR_A),
    )
    assert len(result.hits) == 1


def test_adapter_scope_violation_fails_closed() -> None:
    with pytest.raises(SearchAuthorizationInvariantError):
        search_knowledge(
            FakeSearchPort(make_hit(visibility="private", created_by=ACTOR_B)),
            SearchCommand(query_text="授权检索"),
            access_for(ACTOR_A),
        )
