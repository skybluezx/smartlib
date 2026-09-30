#!/usr/bin/env python3
"""Validate shadow-index IDs/versions before switching readers; retain old indexes."""
from __future__ import annotations

import hashlib
import os
import time
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import psycopg


def index_manifest(client, url, index):
    response = client.post(f"{url}/{index}/_search", params={"scroll": "1m"},
                           json={"size": 1000, "sort": ["_doc"], "_source": ["object_version"]})
    response.raise_for_status()
    page = response.json()
    scroll_id = page.get("_scroll_id")
    pairs = []
    try:
        while page["hits"]["hits"]:
            pairs.extend((hit["_id"], int(hit["_source"]["object_version"])) for hit in page["hits"]["hits"])
            response = client.post(f"{url}/_search/scroll", json={"scroll": "1m", "scroll_id": scroll_id})
            response.raise_for_status()
            page = response.json()
            scroll_id = page.get("_scroll_id", scroll_id)
    finally:
        if scroll_id:
            client.request("DELETE", f"{url}/_search/scroll", json={"scroll_id": [scroll_id]})
    return hashlib.md5(",".join(f"{key}:{version}" for key, version in sorted(pairs)).encode()).hexdigest()


def main():
    database_url = os.environ.get("SMARTLIB_DATABASE_URL") or os.environ["SMARTLIB_PROJECTION_DATABASE_URL"]
    url = os.environ.get("SMARTLIB_OPENSEARCH_URL", "http://opensearch:9200").rstrip("/")
    write = os.environ.get("SMARTLIB_OPENSEARCH_WRITE_ALIAS", "smartlib-knowledge-write")
    read = os.environ.get("SMARTLIB_OPENSEARCH_READ_ALIAS", "smartlib-knowledge-read")
    new = f"smartlib-knowledge-v1-rebuild-{datetime.now(UTC):%Y%m%d%H%M%S}-{uuid4().hex[:6]}"
    trace = f"opensearch-full-rebuild:{uuid4()}"
    with psycopg.connect(database_url) as connection, httpx.Client(timeout=30) as client:
        if not connection.execute("SELECT pg_try_advisory_lock(706420361)").fetchone()[0]:
            raise RuntimeError("Another search rebuild is running")
        connection.commit()
        def aliases(name):
            result = client.get(f"{url}/_alias/{name}")
            result.raise_for_status()
            return sorted(result.json())
        def swap(actions):
            result = client.post(f"{url}/_aliases", json={"actions": actions})
            result.raise_for_status()
        old_write, old_read = aliases(write), aliases(read)
        if len(old_write) != 1:
            raise RuntimeError("Expected exactly one write index")
        result = client.put(f"{url}/{new}")
        result.raise_for_status()
        moved = False
        try:
            moved = True
            swap([{"remove": {"index": old_write[0], "alias": write}},
                  {"add": {"index": new, "alias": write, "is_write_index": True}}])
            connection.execute("SELECT smartlib.request_search_projection_rebuild(%s)", (trace,))
            connection.commit()
            deadline = time.monotonic() + 300
            while time.monotonic() < deadline:
                # Final cutover compares one committed authority snapshot.
                connection.execute("SET LOCAL lock_timeout='3s'")
                expected = connection.execute("SELECT smartlib.lock_search_authority_manifest()").fetchone()[0]
                result = client.post(f"{url}/{new}/_refresh")
                result.raise_for_status()
                if index_manifest(client, url, new) == expected:
                    swap([{"remove": {"index": index, "alias": read}} for index in old_read]
                         + [{"add": {"index": new, "alias": read}}])
                    connection.commit()
                    print({"new_index": new, "retained_indexes": sorted(set(old_read + old_write)),
                           "id_version_manifest_verified": True, "trace_id": trace})
                    return
                connection.rollback()
                time.sleep(1)
            raise TimeoutError("Shadow index did not match authority IDs/versions")
        except BaseException:
            connection.rollback()
            if moved:
                current_write, current_read = aliases(write), aliases(read)
                swap([{"remove": {"index": index, "alias": write}} for index in current_write]
                     + [{"remove": {"index": index, "alias": read}} for index in current_read]
                     + [{"add": {"index": old_write[0], "alias": write, "is_write_index": True}}]
                     + [{"add": {"index": index, "alias": read}} for index in old_read])
                connection.execute("SELECT smartlib.request_search_projection_rebuild(%s)", (f"rollback:{trace}",))
                connection.commit()
            raise


if __name__ == "__main__":
    main()
