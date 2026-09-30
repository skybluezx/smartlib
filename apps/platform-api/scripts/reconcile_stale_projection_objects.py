"""Remove derived-search/graph objects that no longer exist in canonical state."""

from __future__ import annotations

import argparse
import json
import os
from typing import Any
from urllib.parse import quote

import httpx
import psycopg


def path_id(value: Any) -> str:
    return quote(json.dumps(value, ensure_ascii=False), safe="")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--target", choices=("search", "graph", "both"), default="both")
    parser.add_argument("--active-ids", help="newline-delimited canonical object IDs")
    args = parser.parse_args()

    if args.active_ids:
        with open(args.active_ids, encoding="utf-8") as source:
            active_ids = {line.strip() for line in source if line.strip()}
    else:
        database_url = os.environ.get("SMARTLIB_PROJECTION_DATABASE_URL") or os.environ[
            "SMARTLIB_DATABASE_URL"
        ]
        with psycopg.connect(database_url) as connection:
            active_ids = {
                str(row[0])
                for row in connection.execute(
                    "SELECT object_id FROM smartlib.knowledge_object "
                    "WHERE system_to='infinity'::timestamptz"
                )
            }

    search_ids: set[str] = set()
    graph_by_object_id: dict[str, Any] = {}

    with httpx.Client(timeout=60) as client:
        if args.target in {"search", "both"}:
            search_root = os.environ["SMARTLIB_OPENSEARCH_URL"].rstrip("/")
            search_alias = os.environ.get(
                "SMARTLIB_OPENSEARCH_WRITE_ALIAS", "smartlib-knowledge-write"
            )
            search_response = client.post(
                f"{search_root}/{search_alias}/_search",
                json={"size": 10000, "_source": False, "query": {"match_all": {}}},
            )
            search_response.raise_for_status()
            search_ids = {
                str(hit["_id"]) for hit in search_response.json()["hits"]["hits"]
            }
        if args.target in {"graph", "both"}:
            graph_root = os.environ["SMARTLIB_HUGEGRAPH_URL"].rstrip("/")
            graph_name = os.environ.get("SMARTLIB_HUGEGRAPH_GRAPH", "hugegraph")
            graph_base = f"{graph_root}/graphspaces/DEFAULT/graphs/{graph_name}/graph"
            graph_auth = (
                os.environ.get("SMARTLIB_HUGEGRAPH_USER", "admin"),
                os.environ["SMARTLIB_HUGEGRAPH_PASSWORD"],
            )
            graph_response = client.get(
                f"{graph_base}/vertices",
                auth=graph_auth,
                params={"label": "knowledge_object", "limit": 100000},
            )
            graph_response.raise_for_status()
            graph_vertices = graph_response.json()["vertices"]
            graph_by_object_id = {
                str(vertex["properties"]["object_id"]): vertex["id"]
                for vertex in graph_vertices
            }

        stale_search = sorted(search_ids - active_ids)
        stale_graph = sorted(set(graph_by_object_id) - active_ids)
        missing_search = sorted(active_ids - search_ids) if search_ids else []
        missing_graph = sorted(active_ids - set(graph_by_object_id)) if graph_by_object_id else []
        if args.apply:
            for object_id in stale_search:
                response = client.delete(
                    f"{search_root}/{search_alias}/_doc/{object_id}",
                    params={"refresh": "false"},
                )
                if response.status_code != 404:
                    response.raise_for_status()
            if stale_search:
                client.post(f"{search_root}/{search_alias}/_refresh").raise_for_status()
            for object_id in stale_graph:
                client.delete(
                    f"{graph_base}/vertices/{path_id(graph_by_object_id[object_id])}",
                    auth=graph_auth,
                    params={"label": "knowledge_object"},
                ).raise_for_status()

    print(
        json.dumps(
            {
                "applied": args.apply,
                "canonical_active_objects": len(active_ids),
                "search_objects_before": len(search_ids),
                "graph_objects_before": len(graph_by_object_id),
                "stale_search_objects": len(stale_search),
                "stale_graph_objects": len(stale_graph),
                "missing_search_objects": len(missing_search),
                "missing_graph_objects": len(missing_graph),
                "missing_search_object_ids": missing_search[:100],
                "missing_graph_object_ids": missing_graph[:100],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
