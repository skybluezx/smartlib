from datetime import datetime
from time import perf_counter
from typing import Any, Literal
from uuid import UUID

import httpx

from .cursor import decode_offset_cursor, encode_offset_cursor
from .errors import SearchBackendUnavailable, SearchModeUnavailable
from .models import AdapterSearchResult, InternalSearchHit, SearchAccessContext, SearchCommand


class OpenSearchAdapter:
    backend: Literal["opensearch"] = "opensearch"

    def __init__(self, base_url: str, index_alias: str, timeout_seconds: float = 3.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.index_alias = index_alias
        self.timeout_seconds = timeout_seconds

    def search(self, command: SearchCommand, access: SearchAccessContext) -> AdapterSearchResult:
        if command.retrieval_mode != "lexical":
            raise SearchModeUnavailable(
                "semantic and hybrid retrieval require an approved embedding baseline"
            )

        offset = decode_offset_cursor(command.cursor, self.backend)
        access_filter: dict[str, Any] = {
            "bool": {
                "should": [
                    {"term": {"visibility": "public"}},
                    {"term": {"created_by": str(access.actor_id)}},
                ],
                "minimum_should_match": 1,
            }
        }
        filters: list[dict[str, Any]] = [access_filter]
        if command.object_types:
            filters.append({"terms": {"object_type": list(command.object_types)}})

        body = {
            "from": offset,
            "size": command.page_size + 1,
            "track_total_hits": False,
            "_source": {"excludes": ["embedding"]},
            "query": {
                "bool": {
                    "must": [
                        {
                            "multi_match": {
                                "query": command.query_text,
                                "fields": ["canonical_name^4", "aliases^4", "description"],
                                "type": "best_fields",
                            }
                        }
                    ],
                    "filter": filters,
                }
            },
            "aggs": {"object_types": {"terms": {"field": "object_type", "size": 20}}},
        }
        started = perf_counter()
        try:
            response = httpx.post(
                f"{self.base_url}/{self.index_alias}/_search",
                json=body,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise SearchBackendUnavailable("OpenSearch query failed") from exc

        raw_hits = payload.get("hits", {}).get("hits", [])
        has_more = len(raw_hits) > command.page_size
        hits: list[InternalSearchHit] = []
        for raw_hit in raw_hits[: command.page_size]:
            source = raw_hit["_source"]
            hits.append(
                InternalSearchHit(
                    object_id=UUID(source["object_id"]),
                    object_type=source["object_type"],
                    canonical_name=source["canonical_name"],
                    description=source.get("description"),
                    visibility=source["visibility"],
                    created_by=UUID(source["created_by"]),
                    score=float(raw_hit.get("_score") or 0),
                    recall_channels=("lexical",),
                    object_version=int(source["object_version"]),
                    projection_version=source["projection_version"],
                    source_updated_at=datetime.fromisoformat(
                        source["source_updated_at"].replace("Z", "+00:00")
                    ),
                )
            )

        buckets = payload.get("aggregations", {}).get("object_types", {}).get("buckets", [])
        return AdapterSearchResult(
            hits=tuple(hits),
            object_type_facets={bucket["key"]: int(bucket["doc_count"]) for bucket in buckets},
            next_cursor=(
                encode_offset_cursor(self.backend, offset + command.page_size) if has_more else None
            ),
            backend=self.backend,
            took_ms=(perf_counter() - started) * 1000,
        )
