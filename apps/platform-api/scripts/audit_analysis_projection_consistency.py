import hashlib
import json
import os
from collections import Counter

import httpx
import psycopg
from psycopg.rows import dict_row

from smartlib_platform.foundation.config import Settings


def _digest(rows: list[tuple[object, ...]]) -> str:
    payload = "\n".join("|".join(str(value) for value in row) for row in sorted(rows))
    return hashlib.sha256(payload.encode()).hexdigest()


def _hugegraph_rows(settings: Settings, statement: str) -> list[dict[str, object]]:
    endpoint = (
        f"{settings.hugegraph_url.rstrip('/')}/graphspaces/DEFAULT/graphs/"
        f"{settings.hugegraph_graph}/cypher"
    )
    response = httpx.get(
        endpoint,
        auth=(settings.hugegraph_user, settings.hugegraph_password),
        params={"cypher": statement},
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("status", {}).get("code") not in {None, 200}:
        raise RuntimeError("HugeGraph rejected consistency query")
    return payload.get("result", {}).get("data", [])


def main() -> None:
    settings = Settings.from_env()
    database_url = os.environ.get("SMARTLIB_PROJECTION_DATABASE_URL", settings.database_url)
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        connection.execute(
            "SELECT set_config('smartlib.actor_id', %s, false)",
            (str(settings.dev_actor_id),),
        )
        postgres_nodes = connection.execute(
            """SELECT object_id::text AS object_id,version AS object_version
                 FROM smartlib.knowledge_object
                WHERE system_to='infinity'::timestamptz
                  AND smartlib.analysis_state_eligible(review_state)"""
        ).fetchall()
        postgres_edges = connection.execute(
            """SELECT relation.relation_id::text AS relation_id,
                      relation.review_state,relation.version AS relation_version,
                      relation.predicate, relation.subject_id::text AS subject_id,
                      relation.object_id::text AS object_id
                 FROM smartlib.relation_assertion relation
                 JOIN smartlib.knowledge_object subject
                   ON subject.object_id=relation.subject_id
                  AND subject.system_to='infinity'::timestamptz
                  AND smartlib.analysis_state_eligible(subject.review_state)
                 JOIN smartlib.knowledge_object target
                   ON target.object_id=relation.object_id
                  AND target.system_to='infinity'::timestamptz
                  AND smartlib.analysis_state_eligible(target.review_state)
                WHERE relation.object_id IS NOT NULL
                  AND relation.system_to='infinity'::timestamptz
                  AND smartlib.analysis_state_eligible(relation.review_state)"""
        ).fetchall()

    hugegraph_nodes = _hugegraph_rows(
        settings,
        "MATCH (node:knowledge_object) "
        "RETURN node.object_id AS object_id,node.object_version AS object_version",
    )
    hugegraph_edges = _hugegraph_rows(
        settings,
        "MATCH (subject)-[relation:relates]->(target) "
        "RETURN relation.relation_id AS relation_id,"
        "relation.review_state AS review_state,"
        "relation.relation_version AS relation_version,"
        "relation.predicate AS predicate,subject.object_id AS subject_id,target.object_id AS object_id",
    )

    pg_node_rows = [(row["object_id"], int(row["object_version"])) for row in postgres_nodes]
    hg_node_rows = [(row["object_id"], int(row["object_version"])) for row in hugegraph_nodes]
    pg_edge_rows = [
        (row["relation_id"], row["review_state"], int(row["relation_version"]), row["predicate"], row["subject_id"], row["object_id"])
        for row in postgres_edges
    ]
    hg_edge_rows = [
        (row["relation_id"], row["review_state"], int(row["relation_version"]), row["predicate"], row["subject_id"], row["object_id"])
        for row in hugegraph_edges
    ]
    pg_ids = {row[0] for row in pg_edge_rows}
    hg_ids = {row[0] for row in hg_edge_rows}
    report = {
        "missing_relation_ids": sorted(pg_ids - hg_ids),
        "unexpected_relation_ids": sorted(hg_ids - pg_ids),
        "policy": {"pending": True, "approved": True, "rejected": False, "superseded": False},
        "nodes": {
            "postgresql": len(pg_node_rows),
            "hugegraph": len(hg_node_rows),
            "postgresql_digest": _digest(pg_node_rows),
            "hugegraph_digest": _digest(hg_node_rows),
        },
        "edges": {
            "postgresql": len(pg_edge_rows),
            "hugegraph": len(hg_edge_rows),
            "postgresql_digest": _digest(pg_edge_rows),
            "hugegraph_digest": _digest(hg_edge_rows),
            "postgresql_by_state": dict(Counter(row["review_state"] for row in postgres_edges)),
            "hugegraph_by_state": dict(Counter(row["review_state"] for row in hugegraph_edges)),
            "postgresql_by_predicate": dict(Counter(row["predicate"] for row in postgres_edges)),
            "hugegraph_by_predicate": dict(Counter(row["predicate"] for row in hugegraph_edges)),
        },
    }
    report["consistent"] = (
        report["nodes"]["postgresql_digest"] == report["nodes"]["hugegraph_digest"]
        and report["edges"]["postgresql_digest"] == report["edges"]["hugegraph_digest"]
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if not report["consistent"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
