from urllib.parse import urlsplit
from uuid import UUID

import httpx
import pytest

from smartlib_platform.foundation.config import Settings
from smartlib_platform.graph.hugegraph_projection import HugeGraphProjectionWriter
from smartlib_platform.projection.graph_worker import GraphProjectionSettings
from smartlib_platform.projection.worker import ProjectionSettings
from smartlib_platform.search.opensearch_projection import OpenSearchProjectionWriter


@pytest.mark.parametrize(
    ("settings_type", "dsn_variable"),
    [
        (Settings, "SMARTLIB_DATABASE_URL"),
        (ProjectionSettings, "SMARTLIB_PROJECTION_DATABASE_URL"),
        (GraphProjectionSettings, "SMARTLIB_PROJECTION_DATABASE_URL"),
    ],
)
def test_connection_credentials_come_from_private_configuration(monkeypatch, settings_type, dsn_variable):
    monkeypatch.delenv(dsn_variable, raising=False)
    monkeypatch.delenv("SMARTLIB_HUGEGRAPH_PASSWORD", raising=False)
    defaults = settings_type.from_env()
    assert urlsplit(defaults.database_url).password is None
    if hasattr(defaults, "hugegraph_password"):
        assert defaults.hugegraph_password == ""

    # Test-only values; no network connection or database mutation is performed.
    dsn = "postgresql://test_user:test-only-password@localhost:5432/test_db"
    monkeypatch.setenv(dsn_variable, dsn)
    monkeypatch.setenv("SMARTLIB_HUGEGRAPH_PASSWORD", "test-only-graph-password")
    configured = settings_type.from_env()
    assert configured.database_url == dsn
    if hasattr(configured, "hugegraph_password"):
        assert configured.hugegraph_password == "test-only-graph-password"


def test_hugegraph_relation_preserves_generic_context_without_domain_fields(monkeypatch):
    writer = HugeGraphProjectionWriter("http://hugegraph:8080", "admin", "secret")
    captured = {}
    monkeypatch.setattr(writer, "_find_required_node", lambda value: {"id": value})
    monkeypatch.setattr(writer, "_find_one", lambda *args: None)
    monkeypatch.setattr(writer, "_request", lambda method, path, **kwargs: captured.update(kwargs))
    document = {
        "relation_id": "relation", "subject_id": "person", "object_id": "organization",
        "predicate": "person.affiliated_with", "fact_class": "literature_fact",
        "review_state": "approved", "visibility": "public", "created_by": "actor",
        "relation_version": 2, "projection_version": "v2", "context_object_id": "paper",
    }
    writer._upsert_relation(document)
    properties = captured["json_body"]["properties"]
    assert properties["context_object_id"] == "paper"
    assert "source_publication_authorship_id" not in properties


def test_opensearch_projection_does_not_wait_for_each_document_refresh(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_put(url: str, **kwargs) -> httpx.Response:
        captured["params"] = kwargs["params"]
        return httpx.Response(201, request=httpx.Request("PUT", url), json={"result": "created"})

    writer = OpenSearchProjectionWriter("http://opensearch:9200", "smartlib-knowledge-write")
    monkeypatch.setattr(writer._client, "put", fake_put)
    writer._upsert(UUID("10000000-0000-4000-8000-000000000001"), {"object_version": 1})

    assert captured["params"] == {
        "version": 1,
        "version_type": "external_gte",
        "refresh": "false",
    }


def test_hugegraph_projection_reuses_same_node_version_from_process_cache(monkeypatch) -> None:
    writer = HugeGraphProjectionWriter("http://hugegraph:8080", "admin", "secret")
    find_calls: list[str] = []
    request_calls: list[str] = []
    monkeypatch.setattr(
        writer,
        "_find_one",
        lambda collection, key, value: find_calls.append(value) or None,
    )
    monkeypatch.setattr(
        writer,
        "_request",
        lambda method, path, **kwargs: request_calls.append(path) or {"id": "vertex-1"},
    )
    document = {
        "object_id": "10000000-0000-4000-8000-000000000001",
        "object_type": "discipline",
        "canonical_name": "生物学",
        "visibility": "public",
        "created_by": "10000000-0000-4000-8000-000000000002",
        "object_version": 1,
        "projection_version": "graph-projection-v1",
    }

    assert writer._upsert_node(document) == "vertex-1"
    assert writer._upsert_node(document) == "vertex-1"
    assert find_calls == [document["object_id"]]
    assert request_calls == ["vertices"]
