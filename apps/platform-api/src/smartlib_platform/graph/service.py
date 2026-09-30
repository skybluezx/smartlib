from uuid import UUID

from .errors import GraphAuthorizationInvariantError
from .models import (
    GraphAccessContext,
    GraphEdge,
    GraphNode,
    GraphPath,
    InternalGraphEdge,
    InternalGraphNode,
    NeighborhoodCommand,
    NeighborhoodResult,
    PathCommand,
    PathResult,
    RelationExplanation,
)
from .ports import GraphPort


def get_knowledge_neighborhood(
    port: GraphPort, command: NeighborhoodCommand, access: GraphAccessContext
) -> NeighborhoodResult:
    result = port.neighborhood(command, access)
    _validate_graph_scope(result.nodes, result.edges, access)
    return NeighborhoodResult(
        root_object_id=command.root_object_id,
        nodes=[_public_node(node) for node in result.nodes],
        edges=[_public_edge(edge) for edge in result.edges],
        backend=result.backend,
        projection_version=result.projection_version,
        truncated=result.truncated,
        took_ms=result.took_ms,
    )


def find_knowledge_paths(port: GraphPort, command: PathCommand, access: GraphAccessContext) -> PathResult:
    result = port.find_paths(command, access)
    node_ids, edge_ids = _validate_graph_scope(result.nodes, result.edges, access)
    for path in result.paths:
        if not set(path.node_ids) <= node_ids or not set(path.relation_ids) <= edge_ids:
            raise GraphAuthorizationInvariantError("path references rejected graph material")
        if len(path.node_ids) != len(path.relation_ids) + 1:
            raise GraphAuthorizationInvariantError("path shape is invalid")
    return PathResult(
        start_object_id=command.start_object_id,
        end_object_id=command.end_object_id,
        nodes=[_public_node(node) for node in result.nodes],
        edges=[_public_edge(edge) for edge in result.edges],
        paths=[
            GraphPath(node_ids=list(path.node_ids), relation_ids=list(path.relation_ids))
            for path in result.paths
        ],
        backend=result.backend,
        projection_version=result.projection_version,
        took_ms=result.took_ms,
    )


def explain_relation(
    port: GraphPort, relation_id: UUID, access: GraphAccessContext
) -> RelationExplanation | None:
    result = port.explain_relation(relation_id, access)
    if result is None:
        return None
    _validate_graph_scope((result.subject, result.object), (result.edge,), access)
    return RelationExplanation(
        edge=_public_edge(result.edge),
        subject=_public_node(result.subject),
        object=_public_node(result.object),
        backend=result.backend,
        projection_version=result.projection_version,
    )


def _validate_graph_scope(
    nodes: tuple[InternalGraphNode, ...],
    edges: tuple[InternalGraphEdge, ...],
    access: GraphAccessContext,
) -> tuple[set[UUID], set[UUID]]:
    node_ids: set[UUID] = set()
    for node in nodes:
        if node.visibility != "public" and node.created_by != access.actor_id:
            raise GraphAuthorizationInvariantError("graph adapter returned an unauthorized node")
        node_ids.add(node.object_id)
    edge_ids: set[UUID] = set()
    for edge in edges:
        if edge.visibility != "public" and edge.created_by != access.actor_id:
            raise GraphAuthorizationInvariantError("graph adapter returned an unauthorized edge")
        if edge.subject_id not in node_ids or edge.object_id not in node_ids:
            raise GraphAuthorizationInvariantError("graph edge has a hidden endpoint")
        edge_ids.add(edge.relation_id)
    return node_ids, edge_ids


def _public_node(node: InternalGraphNode) -> GraphNode:
    return GraphNode.model_validate(node.model_dump(exclude={"visibility", "created_by"}))


def _public_edge(edge: InternalGraphEdge) -> GraphEdge:
    return GraphEdge.model_validate(edge.model_dump(exclude={"visibility", "created_by"}))
