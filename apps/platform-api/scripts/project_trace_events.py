#!/usr/bin/env python3
"""Immediately deliver all outbox events for one controlled-import trace."""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, cast
from uuid import UUID

from psycopg import connect
from psycopg.rows import dict_row

from smartlib_platform.graph.hugegraph_projection import HugeGraphProjectionWriter
from smartlib_platform.search.opensearch_projection import OpenSearchProjectionWriter


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-id")
    parser.add_argument("--event", action="append", default=[], help="event_uuid:aggregate_type")
    args = parser.parse_args()
    database_url = os.environ["SMARTLIB_PROJECTION_DATABASE_URL"]
    search = OpenSearchProjectionWriter(
        os.environ["SMARTLIB_OPENSEARCH_URL"],
        os.environ.get("SMARTLIB_OPENSEARCH_WRITE_ALIAS", "smartlib-knowledge-write"),
    )
    graph = HugeGraphProjectionWriter(
        os.environ["SMARTLIB_HUGEGRAPH_URL"],
        os.environ.get("SMARTLIB_HUGEGRAPH_USER", "admin"),
        os.environ["SMARTLIB_HUGEGRAPH_PASSWORD"],
        os.environ.get("SMARTLIB_HUGEGRAPH_GRAPH", "hugegraph"),
    )
    if args.event:
        events = [
            {"event_id": UUID(value.split(":", 1)[0]), "aggregate_type": value.split(":", 1)[1]}
            for value in args.event
        ]
    else:
        if not args.trace_id:
            raise ValueError("provide --trace-id or one or more --event values")
        with connect(database_url, row_factory=dict_row) as connection:
            events = connection.execute(
                """SELECT event_id,aggregate_type FROM smartlib.outbox_event
                    WHERE trace_id=%s ORDER BY occurred_at,event_id""",
                (args.trace_id,),
            ).fetchall()

    counts = {"events": len(events), "search": 0, "graph": 0}
    for event in events:
        event_id = event["event_id"]
        if event["aggregate_type"] == "knowledge_object":
            with connect(database_url, row_factory=dict_row) as connection:
                row = connection.execute(
                    "SELECT smartlib_projection.refresh_postgres_search_event(%s) AS delivery",
                    (event_id,),
                ).fetchone()
                search.deliver(cast(dict[str, Any], row["delivery"]))
                connection.execute(
                    "SELECT smartlib_projection.acknowledge_search_event('opensearch_search',%s)",
                    (event_id,),
                )
                connection.commit()
                counts["search"] += 1

        with connect(database_url, row_factory=dict_row) as connection:
            row = connection.execute(
                "SELECT smartlib_projection.graph_delivery_json(%s) AS delivery",
                (event_id,),
            ).fetchone()
            graph.deliver(cast(dict[str, Any], row["delivery"]))
            connection.execute(
                "SELECT smartlib_projection.acknowledge_graph_event('hugegraph_graph',%s)",
                (event_id,),
            )
            connection.commit()
            counts["graph"] += 1
    print(json.dumps(counts, ensure_ascii=False))


if __name__ == "__main__":
    main()
