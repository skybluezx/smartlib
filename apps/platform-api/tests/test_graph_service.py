from uuid import UUID

import pytest

from smartlib_platform.graph.errors import GraphAuthorizationInvariantError
from smartlib_platform.graph.models import (
    AdapterNeighborhoodResult,
    GraphAccessContext,
    InternalGraphEdge,
    InternalGraphNode,
    NeighborhoodCommand,
)
from smartlib_platform.graph.service import get_knowledge_neighborhood
from smartlib_platform.graph.postgres import PostgresGraphAdapter

ACTOR_A = UUID("10000000-0000-0000-0000-000000000001")
ACTOR_B = UUID("10000000-0000-0000-0000-000000000002")
NODE_A = UUID("30000000-0000-0000-0000-000000000001")
NODE_B = UUID("30000000-0000-0000-0000-000000000002")
RELATION = UUID("40000000-0000-0000-0000-000000000001")


def test_complete_one_hop_does_not_apply_graph_limit(monkeypatch):
    adapter = PostgresGraphAdapter(None, complete_one_hop=True)
    nodes = {value: node(value, visibility='campus', created_by=ACTOR_A) for value in (NODE_A, NODE_B)}
    edges = [edge(visibility='campus', created_by=ACTOR_A).model_copy(update={'relation_id': UUID(int=i+1)}) for i in range(250)]
    monkeypatch.setattr(adapter, '_load_nodes', lambda ids: {key: nodes[key] for key in ids})
    def load_edges(frontier, direction, predicates, limit):
        assert limit is None
        return edges
    monkeypatch.setattr(adapter, '_load_edges', load_edges)
    result = get_knowledge_neighborhood(adapter, NeighborhoodCommand(root_object_id=NODE_A, limit=30),
        GraphAccessContext(actor_id=ACTOR_A, purpose='test', trace_id='test'))
    assert len(result.edges) == 250
    assert result.truncated is False


class FakeGraphPort:
    def __init__(self, nodes: tuple[InternalGraphNode, ...], edge: InternalGraphEdge) -> None:
        self.nodes = nodes
        self.edge = edge

    def neighborhood(self, command, access) -> AdapterNeighborhoodResult:  # type: ignore[no-untyped-def]
        return AdapterNeighborhoodResult(
            nodes=self.nodes,
            edges=(self.edge,),
            backend="fake",
            took_ms=1,
        )


def node(object_id: UUID, *, visibility: str, created_by: UUID) -> InternalGraphNode:
    return InternalGraphNode(
        object_id=object_id,
        object_type="person",
        canonical_name=str(object_id),
        description=None,
        object_version=1,
        projection_version="graph-projection-v1",
        visibility=visibility,
        created_by=created_by,  # type: ignore[arg-type]
    )


def edge(*, visibility: str, created_by: UUID) -> InternalGraphEdge:
    return InternalGraphEdge(
        relation_id=RELATION,
        subject_id=NODE_A,
        object_id=NODE_B,
        predicate="cooperates_with",
        fact_class="human_confirmed",
        confidence=1,
        review_state="approved",
        evidence_ids=[],
        relation_version=1,
        projection_version="graph-projection-v1",
        visibility=visibility,
        created_by=created_by,  # type: ignore[arg-type]
    )


def access() -> GraphAccessContext:
    return GraphAccessContext(actor_id=ACTOR_A, purpose="interactive_graph", trace_id="test")


def test_graph_service_removes_internal_access_fields() -> None:
    result = get_knowledge_neighborhood(
        FakeGraphPort(
            (
                node(NODE_A, visibility="private", created_by=ACTOR_A),
                node(NODE_B, visibility="public", created_by=ACTOR_B),
            ),
            edge(visibility="public", created_by=ACTOR_B),
        ),
        NeighborhoodCommand(root_object_id=NODE_A),
        access(),
    )
    assert len(result.edges) == 1
    assert "visibility" not in result.nodes[0].model_dump()
    assert "created_by" not in result.edges[0].model_dump()


def test_graph_service_rejects_hidden_intermediate_node() -> None:
    with pytest.raises(GraphAuthorizationInvariantError):
        get_knowledge_neighborhood(
            FakeGraphPort(
                (
                    node(NODE_A, visibility="private", created_by=ACTOR_A),
                    node(NODE_B, visibility="private", created_by=ACTOR_B),
                ),
                edge(visibility="public", created_by=ACTOR_B),
            ),
            NeighborhoodCommand(root_object_id=NODE_A),
            access(),
        )


def test_graph_service_rejects_edge_with_missing_endpoint() -> None:
    with pytest.raises(GraphAuthorizationInvariantError):
        get_knowledge_neighborhood(
            FakeGraphPort(
                (node(NODE_A, visibility="private", created_by=ACTOR_A),),
                edge(visibility="public", created_by=ACTOR_B),
            ),
            NeighborhoodCommand(root_object_id=NODE_A),
            access(),
        )
