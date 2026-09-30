import argparse
import time
from dataclasses import dataclass
from os import environ
from typing import Any, Literal, cast

from psycopg import connect
from psycopg.rows import dict_row

from smartlib_platform.search.opensearch_projection import OpenSearchProjectionWriter

ProjectionTarget = Literal["postgres", "opensearch", "both"]


@dataclass(frozen=True)
class ProjectionSettings:
    database_url: str
    target: ProjectionTarget
    batch_size: int
    poll_seconds: float
    opensearch_url: str
    opensearch_write_alias: str

    @classmethod
    def from_env(cls) -> ProjectionSettings:
        target = environ.get("SMARTLIB_SEARCH_PROJECTION_TARGET", "postgres")
        if target not in {"postgres", "opensearch", "both"}:
            raise ValueError("SMARTLIB_SEARCH_PROJECTION_TARGET must be postgres, opensearch or both")
        return cls(
            database_url=environ.get(
                "SMARTLIB_PROJECTION_DATABASE_URL",
                "postgresql://smartlib_projection_worker@localhost:5432/smartlib",
            ),
            target=cast(ProjectionTarget, target),
            batch_size=min(max(int(environ.get("SMARTLIB_PROJECTION_BATCH_SIZE", "100")), 1), 1000),
            poll_seconds=max(float(environ.get("SMARTLIB_PROJECTION_POLL_SECONDS", "1")), 0.1),
            opensearch_url=environ.get("SMARTLIB_OPENSEARCH_URL", "http://localhost:9200"),
            opensearch_write_alias=environ.get("SMARTLIB_OPENSEARCH_WRITE_ALIAS", "smartlib-knowledge-write"),
        )


class SearchProjectionWorker:
    def __init__(self, settings: ProjectionSettings) -> None:
        self.settings = settings
        self.opensearch = (
            OpenSearchProjectionWriter(settings.opensearch_url, settings.opensearch_write_alias)
            if settings.target in {"opensearch", "both"}
            else None
        )

    def run_once(self) -> int:
        projection_name = "opensearch_search" if self.opensearch else "postgres_search"
        with connect(self.settings.database_url, row_factory=dict_row) as connection:
            events = connection.execute(
                "SELECT * FROM smartlib_projection.pending_search_events(%s, %s)",
                (projection_name, self.settings.batch_size),
            ).fetchall()

        processed = 0
        for event in events:
            with connect(self.settings.database_url, row_factory=dict_row) as connection:
                delivery_row = connection.execute(
                    "SELECT smartlib_projection.refresh_postgres_search_event(%s) AS delivery",
                    (event["event_id"],),
                ).fetchone()
                if delivery_row is None:
                    raise RuntimeError("projection refresh returned no delivery")
                delivery = cast(dict[str, Any], delivery_row["delivery"])
                if self.opensearch:
                    self.opensearch.deliver(delivery)
                    connection.execute(
                        "SELECT smartlib_projection.acknowledge_search_event(%s, %s)",
                        ("opensearch_search", event["event_id"]),
                    )
                connection.commit()
            processed += 1
        return processed

    def run_forever(self) -> None:
        while True:
            processed = self.run_once()
            if processed == 0:
                time.sleep(self.settings.poll_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description="Project SmartLib Outbox events into search indexes")
    parser.add_argument("--once", action="store_true", help="process one batch and exit")
    arguments = parser.parse_args()
    worker = SearchProjectionWorker(ProjectionSettings.from_env())
    if arguments.once:
        worker.run_once()
    else:
        worker.run_forever()


if __name__ == "__main__":
    main()
