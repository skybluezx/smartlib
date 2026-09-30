"""Catch up HugeGraph from current canonical state after a large controlled import."""

from __future__ import annotations

import argparse
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, cast

from psycopg import connect
from psycopg.rows import dict_row

from smartlib_platform.graph.hugegraph_projection import HugeGraphProjectionWriter


def process_group(group: dict[str, Any]) -> int:
    writer = HugeGraphProjectionWriter(
        os.environ["SMARTLIB_HUGEGRAPH_URL"],
        os.environ.get("SMARTLIB_HUGEGRAPH_USER", "admin"),
        os.environ["SMARTLIB_HUGEGRAPH_PASSWORD"],
        os.environ.get("SMARTLIB_HUGEGRAPH_GRAPH", "hugegraph"),
    )
    database_url = os.environ["SMARTLIB_PROJECTION_DATABASE_URL"]
    with connect(database_url, row_factory=dict_row) as connection:
        row = connection.execute(
            "SELECT smartlib_projection.graph_delivery_json(%s) AS delivery",
            (group["event_ids"][0],),
        ).fetchone()
        if row is None:
            raise RuntimeError("graph delivery returned no row")
        writer.deliver(cast(dict[str, Any], row["delivery"]))
        connection.execute(
            "SELECT smartlib_projection.acknowledge_graph_events(%s,%s)",
            ("hugegraph_graph", group["event_ids"]),
        )
        connection.commit()
    return len(group["event_ids"])


def pending_groups(limit: int) -> list[dict[str, Any]]:
    with connect(os.environ["SMARTLIB_PROJECTION_DATABASE_URL"], row_factory=dict_row) as connection:
        return connection.execute(
            "SELECT * FROM smartlib_projection.pending_graph_event_groups(%s,%s)",
            ("hugegraph_graph", limit),
        ).fetchall()


def main() -> None:
    parser = argparse.ArgumentParser(description="并发追平 PostgreSQL 到 HugeGraph 的当前投影")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--batch-size", type=int, default=600)
    args = parser.parse_args()
    groups_done = 0
    events_done = 0
    while groups := pending_groups(args.batch_size):
        with ThreadPoolExecutor(max_workers=max(1, min(args.workers, 12))) as executor:
            futures = [executor.submit(process_group, group) for group in groups]
            for future in as_completed(futures):
                events_done += future.result()
                groups_done += 1
        print(f"groups={groups_done} events={events_done}", flush=True)
    print(f"SMARTLIB_GRAPH_CATCHUP_OK groups={groups_done} events={events_done}")


if __name__ == "__main__":
    main()
