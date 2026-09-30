import argparse
import time
from dataclasses import dataclass
from os import environ
from typing import Any, cast

from psycopg import connect
from psycopg.rows import dict_row

from smartlib_platform.graph.hugegraph_projection import HugeGraphProjectionWriter


@dataclass(frozen=True)
class GraphProjectionSettings:
    database_url: str
    batch_size: int
    poll_seconds: float
    hugegraph_url: str
    hugegraph_user: str
    hugegraph_password: str
    hugegraph_graph: str

    @classmethod
    def from_env(cls) -> GraphProjectionSettings:
        return cls(
            database_url=environ.get(
                "SMARTLIB_PROJECTION_DATABASE_URL",
                "postgresql://smartlib_projection_worker@localhost:5432/smartlib",
            ),
            batch_size=min(max(int(environ.get("SMARTLIB_PROJECTION_BATCH_SIZE", "100")), 1), 1000),
            poll_seconds=max(float(environ.get("SMARTLIB_PROJECTION_POLL_SECONDS", "1")), 0.1),
            hugegraph_url=environ.get("SMARTLIB_HUGEGRAPH_URL", "http://localhost:8080"),
            hugegraph_user=environ.get("SMARTLIB_HUGEGRAPH_USER", "admin"),
            hugegraph_password=environ.get("SMARTLIB_HUGEGRAPH_PASSWORD", ""),
            hugegraph_graph=environ.get("SMARTLIB_HUGEGRAPH_GRAPH", "hugegraph"),
        )


class GraphProjectionWorker:
    def __init__(self, settings: GraphProjectionSettings) -> None:
        self.settings = settings
        self.writer = HugeGraphProjectionWriter(
            settings.hugegraph_url,
            settings.hugegraph_user,
            settings.hugegraph_password,
            settings.hugegraph_graph,
        )

    def run_once(self) -> int:
        with connect(self.settings.database_url, row_factory=dict_row) as connection:
            events = connection.execute(
                "SELECT * FROM smartlib_projection.pending_graph_events(%s, %s)",
                ("hugegraph_graph", self.settings.batch_size),
            ).fetchall()
        processed = 0
        for event in events:
            with connect(self.settings.database_url, row_factory=dict_row) as connection:
                row = connection.execute(
                    "SELECT smartlib_projection.graph_delivery_json(%s) AS delivery",
                    (event["event_id"],),
                ).fetchone()
                if row is None:
                    raise RuntimeError("graph delivery returned no row")
                self.writer.deliver(cast(dict[str, Any], row["delivery"]))
                connection.execute(
                    "SELECT smartlib_projection.acknowledge_graph_event(%s, %s)",
                    ("hugegraph_graph", event["event_id"]),
                )
                connection.commit()
            processed += 1
        return processed

    def run_forever(self) -> None:
        while True:
            if self.run_once() == 0:
                time.sleep(self.settings.poll_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description="Project SmartLib Outbox events into HugeGraph")
    parser.add_argument("--once", action="store_true", help="process one batch and exit")
    arguments = parser.parse_args()
    worker = GraphProjectionWorker(GraphProjectionSettings.from_env())
    if arguments.once:
        worker.run_once()
    else:
        worker.run_forever()


if __name__ == "__main__":
    main()
