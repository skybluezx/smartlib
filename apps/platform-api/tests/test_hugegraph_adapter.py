from uuid import UUID

import httpx
import pytest
from pydantic import ValidationError

from smartlib_platform.graph.hugegraph import (
    HugeGraphAdapter,
    _edge,
    _node,
    _secure_custom_scope_statement,
)
from smartlib_platform.graph.hugegraph_projection import HugeGraphProjectionWriter
from smartlib_platform.graph.models import GraphAccessContext, NeighborhoodCommand

ACTOR = UUID("10000000-0000-0000-0000-000000000001")
ROOT = UUID("30000000-0000-0000-0000-000000000001")


@pytest.mark.parametrize(
    "description", [{}, {"description": None}, {"description": ""}, {"description": "论文说明"}]
)
def test_neighborhood_accepts_absent_or_nullable_description(monkeypatch, description) -> None:
    document = {
        "object_id": str(ROOT), "object_type": "publication", "canonical_name": "Paper",
        "object_version": 1, "projection_version": "graph-projection-v1",
        "visibility": "restricted", "created_by": str(ACTOR), **description,
    }
    original = dict(document)
    adapter = HugeGraphAdapter("http://hugegraph:8080", "admin", "secret")
    monkeypatch.setattr(adapter, "_query", lambda _: [{"node_docs": [document], "edge_docs": []}])
    result = adapter.neighborhood(
        NeighborhoodCommand(root_object_id=ROOT, max_depth=1),
        GraphAccessContext(actor_id=ACTOR, purpose="interactive_graph", trace_id="test"),
    )
    assert result.nodes[0].description == description.get("description")
    assert document == original


def test_missing_description_does_not_disable_required_node_validation() -> None:
    with pytest.raises(ValidationError):
        _node({"object_id": str(ROOT)})


@pytest.mark.parametrize("confidence", [{}, {"confidence": None}, {"confidence": 0.0}, {"confidence": 0.9}])
def test_edge_accepts_missing_confidence_without_inventing_score(confidence) -> None:
    document = {
        "relation_id": str(ROOT), "subject_id": str(ACTOR), "object_id": str(ROOT),
        "predicate": "person.authored", "fact_class": "literature_fact", "review_state": "approved",
        "relation_version": 1, "projection_version": "graph-projection-v1",
        "visibility": "restricted", "created_by": str(ACTOR), **confidence,
    }
    original = dict(document)
    result = _edge(document, ACTOR)
    assert result.confidence == confidence.get("confidence")
    assert document == original


def test_hugegraph_query_filters_every_node_and_relationship(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_get(url: str, **kwargs) -> httpx.Response:
        captured["url"] = url
        captured["params"] = kwargs["params"]
        return httpx.Response(
            200,
            request=httpx.Request("GET", url),
            json={"result": {"data": []}},
        )

    monkeypatch.setattr(httpx, "get", fake_get)
    adapter = HugeGraphAdapter("http://hugegraph:8080", "admin", "secret")
    adapter.neighborhood(
        NeighborhoodCommand(root_object_id=ROOT, predicates=["cooperates_with"], max_depth=2),
        GraphAccessContext(actor_id=ACTOR, purpose="interactive_graph", trace_id="test"),
    )
    statement = str(captured["params"])
    assert captured["url"] == ("http://hugegraph:8080/graphspaces/DEFAULT/graphs/hugegraph/cypher")
    assert "root.access_scope" in statement
    assert "r1.access_scope" in statement
    assert "access_scope" in statement
    assert str(ACTOR) in statement
    assert "cooperates_with" in statement
    assert "r2:relates" in statement


def test_custom_scope_query_is_read_only_scoped_and_bounded() -> None:
    query = """MATCH (scholar:knowledge_object)-[authored:relates]->(publication:knowledge_object)
WHERE scholar.object_type = 'person'
  AND authored.predicate = 'person.authored'
  AND publication.object_type = 'publication'
RETURN DISTINCT publication.object_id AS publication_id"""

    statement = _secure_custom_scope_statement(query, ACTOR, 5000)

    assert "scholar.access_scope" in statement
    assert "authored.access_scope" in statement
    assert "publication.access_scope" in statement
    assert str(ACTOR) in statement
    assert statement.endswith("LIMIT 5001")


@pytest.mark.parametrize(
    "query",
    [
        "MATCH (publication:knowledge_object) DELETE publication RETURN publication.object_id",
        "MATCH (publication:knowledge_object) RETURN publication.canonical_name AS title",
        "MATCH (publication:knowledge_object)-[:relates*1..3]->(other:knowledge_object) "
        "RETURN publication.object_id AS publication_id",
        "CALL db.schema() RETURN publication.object_id AS publication_id",
    ],
)
def test_custom_scope_query_rejects_unsafe_or_wrong_shape(query: str) -> None:
    with pytest.raises(ValueError):
        _secure_custom_scope_statement(query, ACTOR, 5000)


def test_projection_delete_uses_unquoted_composite_edge_id(monkeypatch) -> None:
    writer = HugeGraphProjectionWriter("http://hugegraph:8080", "admin", "secret")
    edge_id = '"S1:source>1>1>relation>S1:target"'
    calls: list[tuple[str, str]] = []

    monkeypatch.setattr(
        writer,
        "_find_one",
        lambda collection, key, value: {"id": edge_id},
    )
    monkeypatch.setattr(
        writer,
        "_request",
        lambda method, path, **kwargs: calls.append((method, path)),
    )

    writer._delete_relation("relation-id")

    assert calls == [("DELETE", "edges/S1%3Asource%3E1%3E1%3Erelation%3ES1%3Atarget")]
