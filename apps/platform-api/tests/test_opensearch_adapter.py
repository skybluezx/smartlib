import json
from uuid import UUID

import httpx

from smartlib_platform.search.models import SearchAccessContext, SearchCommand
from smartlib_platform.search.opensearch import OpenSearchAdapter

ACTOR = UUID("10000000-0000-0000-0000-000000000001")


def test_opensearch_query_applies_access_filter_before_retrieval(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_post(url: str, **kwargs) -> httpx.Response:
        captured["url"] = url
        captured["body"] = kwargs["json"]
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "hits": {"hits": []},
                "aggregations": {"object_types": {"buckets": []}},
            },
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    adapter = OpenSearchAdapter("http://opensearch:9200", "smartlib-knowledge-read")
    adapter.search(
        SearchCommand(query_text="人工智能", object_types=["publication"]),
        SearchAccessContext(actor_id=ACTOR, purpose="interactive_search", trace_id="test"),
    )

    serialized = json.dumps(captured["body"], ensure_ascii=False)
    assert '"visibility": "public"' in serialized
    assert str(ACTOR) in serialized
    assert '"object_type": ["publication"]' in serialized
    assert "embedding" in serialized
