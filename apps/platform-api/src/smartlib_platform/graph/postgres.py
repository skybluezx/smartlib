from collections.abc import Iterable
from time import perf_counter
from uuid import UUID

from smartlib_platform.foundation.database import DbConnection

from .models import (
    AdapterNeighborhoodResult,
    AdapterPathResult,
    AdapterRelationExplanation,
    GraphAccessContext,
    InternalGraphEdge,
    InternalGraphNode,
    InternalGraphPath,
    NeighborhoodCommand,
    PathCommand,
)


class PostgresGraphAdapter:
    """Correctness baseline over canonical relations; RLS is active on this connection."""

    backend_name = "postgres"
    projection_version = "canonical-graph-v1"

    def __init__(self, connection: DbConnection, *, complete_one_hop: bool = False) -> None:
        self.connection = connection
        self.complete_one_hop = complete_one_hop

    def neighborhood(
        self, command: NeighborhoodCommand, access: GraphAccessContext
    ) -> AdapterNeighborhoodResult:
        del access
        started = perf_counter()
        nodes = self._load_nodes({command.root_object_id})
        if command.root_object_id not in nodes:
            return AdapterNeighborhoodResult(
                nodes=(),
                edges=(),
                backend=self.backend_name,
                projection_version=self.projection_version,
                took_ms=_elapsed_ms(started),
            )

        frontier = {command.root_object_id}
        if self.complete_one_hop:
            candidates = self._load_edges(frontier, command.direction, command.predicates, None)
            nodes.update(self._load_nodes({endpoint for edge in candidates for endpoint in (edge.subject_id, edge.object_id)}))
            return AdapterNeighborhoodResult(
                nodes=tuple(nodes.values()),
                edges=tuple(edge for edge in candidates if edge.subject_id in nodes and edge.object_id in nodes),
                backend=self.backend_name, projection_version=self.projection_version,
                truncated=False, took_ms=_elapsed_ms(started),
            )
        visited = set(frontier)
        edges: dict[UUID, InternalGraphEdge] = {}
        truncated = False
        for _ in range(command.max_depth):
            candidates = self._load_edges(frontier, command.direction, command.predicates, command.limit + 1)
            if len(candidates) > command.limit:
                truncated = True
            endpoint_ids = {
                endpoint
                for edge in candidates[: command.limit]
                for endpoint in (edge.subject_id, edge.object_id)
            }
            loaded_nodes = self._load_nodes(endpoint_ids)
            next_frontier: set[UUID] = set()
            for edge in candidates[: command.limit]:
                if edge.subject_id not in loaded_nodes or edge.object_id not in loaded_nodes:
                    continue
                candidate_ids = {edge.subject_id, edge.object_id} - frontier
                if command.object_types and any(
                    loaded_nodes[node_id].object_type not in command.object_types for node_id in candidate_ids
                ):
                    continue
                edges[edge.relation_id] = edge
                nodes.update(loaded_nodes)
                next_frontier.update(candidate_ids - visited)
                if len(edges) >= command.limit:
                    truncated = truncated or bool(next_frontier)
                    break
            visited.update(next_frontier)
            frontier = next_frontier
            if not frontier or len(edges) >= command.limit:
                break

        used_node_ids = {command.root_object_id} | {
            endpoint for edge in edges.values() for endpoint in (edge.subject_id, edge.object_id)
        }
        return AdapterNeighborhoodResult(
            nodes=tuple(nodes[node_id] for node_id in sorted(used_node_ids, key=str)),
            edges=tuple(edges[edge_id] for edge_id in sorted(edges, key=str)),
            backend=self.backend_name,
            projection_version=self.projection_version,
            truncated=truncated,
            took_ms=_elapsed_ms(started),
        )

    def find_paths(self, command: PathCommand, access: GraphAccessContext) -> AdapterPathResult:
        del access
        started = perf_counter()
        nodes = self._load_nodes({command.start_object_id, command.end_object_id})
        if command.start_object_id not in nodes or command.end_object_id not in nodes:
            return AdapterPathResult(
                nodes=(),
                edges=(),
                paths=(),
                backend=self.backend_name,
                projection_version=self.projection_version,
                took_ms=_elapsed_ms(started),
            )

        queue: list[InternalGraphPath] = [
            InternalGraphPath(node_ids=(command.start_object_id,), relation_ids=())
        ]
        results: list[InternalGraphPath] = []
        edges: dict[UUID, InternalGraphEdge] = {}
        while queue and len(results) < command.limit:
            path = queue.pop(0)
            if len(path.relation_ids) >= command.max_depth:
                continue
            current = path.node_ids[-1]
            candidates = self._load_edges({current}, command.direction, command.predicates, 500)
            endpoint_ids = {endpoint for edge in candidates for endpoint in (edge.subject_id, edge.object_id)}
            nodes.update(self._load_nodes(endpoint_ids))
            for edge in candidates:
                next_id = _next_node(edge, current, command.direction)
                if next_id is None or next_id in path.node_ids or next_id not in nodes:
                    continue
                next_path = InternalGraphPath(
                    node_ids=(*path.node_ids, next_id),
                    relation_ids=(*path.relation_ids, edge.relation_id),
                )
                edges[edge.relation_id] = edge
                if next_id == command.end_object_id:
                    results.append(next_path)
                    if len(results) >= command.limit:
                        break
                else:
                    queue.append(next_path)

        used_node_ids = {node_id for path in results for node_id in path.node_ids}
        used_edge_ids = {edge_id for path in results for edge_id in path.relation_ids}
        return AdapterPathResult(
            nodes=tuple(nodes[node_id] for node_id in sorted(used_node_ids, key=str)),
            edges=tuple(edges[edge_id] for edge_id in sorted(used_edge_ids, key=str)),
            paths=tuple(results),
            backend=self.backend_name,
            projection_version=self.projection_version,
            took_ms=_elapsed_ms(started),
        )

    def explain_relation(
        self, relation_id: UUID, access: GraphAccessContext
    ) -> AdapterRelationExplanation | None:
        del access
        edges = self._load_edges_by_id(relation_id)
        if not edges:
            return None
        edge = edges[0]
        nodes = self._load_nodes({edge.subject_id, edge.object_id})
        if edge.subject_id not in nodes or edge.object_id not in nodes:
            return None
        return AdapterRelationExplanation(
            edge=edge,
            subject=nodes[edge.subject_id],
            object=nodes[edge.object_id],
            backend=self.backend_name,
            projection_version=self.projection_version,
        )

    def _load_nodes(self, object_ids: Iterable[UUID]) -> dict[UUID, InternalGraphNode]:
        ids = list(set(object_ids))
        if not ids:
            return {}
        rows = self.connection.execute(
            """SELECT object_id, object_type, canonical_name, description, version AS object_version,
                      visibility, created_by, %s AS projection_version
               FROM smartlib.knowledge_object
               WHERE object_id = ANY(%s)
                 AND smartlib.analysis_state_eligible(review_state)
                 AND system_to = 'infinity'::timestamptz""",
            (self.projection_version, ids),
        ).fetchall()
        return {row["object_id"]: InternalGraphNode.model_validate(row) for row in rows}

    def _load_edges(
        self,
        frontier: set[UUID],
        direction: str,
        predicates: list[str],
        limit: int | None,
    ) -> list[InternalGraphEdge]:
        if not frontier:
            return []
        if direction == "outgoing":
            connectivity = "relation.subject_id = ANY(%s)"
            parameters: list[object] = [self.projection_version, list(frontier)]
        elif direction == "incoming":
            connectivity = "relation.object_id = ANY(%s)"
            parameters = [self.projection_version, list(frontier)]
        else:
            connectivity = "(relation.subject_id = ANY(%s) OR relation.object_id = ANY(%s))"
            parameters = [self.projection_version, list(frontier), list(frontier)]
        predicate_sql = ""
        if predicates:
            predicate_sql = " AND relation.predicate = ANY(%s)"
            parameters.append(predicates)
        parameters.append(limit)
        rows = self.connection.execute(
            f"""SELECT relation.relation_id, relation.subject_id, relation.object_id,
                       relation.predicate, relation.fact_class, relation.confidence,
                       relation.review_state, relation.visibility, relation.created_by,
                       relation.attributes,
                       relation.version AS relation_version,
                       COALESCE(array_agg(evidence.evidence_id ORDER BY evidence.evidence_id)
                           FILTER (WHERE evidence.evidence_id IS NOT NULL), ARRAY[]::uuid[]) AS evidence_ids,
                       %s AS projection_version
                FROM smartlib.relation_assertion AS relation
                JOIN smartlib.knowledge_object AS subject ON subject.object_id = relation.subject_id
                JOIN smartlib.knowledge_object AS object ON object.object_id = relation.object_id
                LEFT JOIN smartlib.relation_evidence AS link ON link.relation_id = relation.relation_id
                LEFT JOIN smartlib.evidence_record AS evidence ON evidence.evidence_id = link.evidence_id
                WHERE {connectivity}{predicate_sql}
                  AND relation.object_id IS NOT NULL
                  AND smartlib.analysis_state_eligible(relation.review_state)
                  AND relation.system_to = 'infinity'::timestamptz
                  AND subject.system_to = 'infinity'::timestamptz
                  AND object.system_to = 'infinity'::timestamptz
                  AND smartlib.analysis_state_eligible(subject.review_state)
                  AND smartlib.analysis_state_eligible(object.review_state)
                GROUP BY relation.relation_id
                ORDER BY relation.relation_id
                LIMIT %s""",
            tuple(parameters),
        ).fetchall()
        return [InternalGraphEdge.model_validate(row) for row in rows]

    def _load_edges_by_id(self, relation_id: UUID) -> list[InternalGraphEdge]:
        rows = self.connection.execute(
            """SELECT relation.relation_id, relation.subject_id, relation.object_id,
                      relation.predicate, relation.fact_class, relation.confidence,
                      relation.review_state, relation.visibility, relation.created_by,
                      relation.attributes,
                      relation.version AS relation_version,
                      COALESCE(array_agg(evidence.evidence_id ORDER BY evidence.evidence_id)
                          FILTER (WHERE evidence.evidence_id IS NOT NULL), ARRAY[]::uuid[]) AS evidence_ids,
                      %s AS projection_version
               FROM smartlib.relation_assertion AS relation
               JOIN smartlib.knowledge_object AS subject ON subject.object_id = relation.subject_id
               JOIN smartlib.knowledge_object AS object ON object.object_id = relation.object_id
               LEFT JOIN smartlib.relation_evidence AS link ON link.relation_id = relation.relation_id
               LEFT JOIN smartlib.evidence_record AS evidence ON evidence.evidence_id = link.evidence_id
               WHERE relation.relation_id = %s AND relation.object_id IS NOT NULL
                 AND smartlib.analysis_state_eligible(relation.review_state)
                 AND relation.system_to = 'infinity'::timestamptz
                 AND subject.system_to = 'infinity'::timestamptz
                 AND object.system_to = 'infinity'::timestamptz
                 AND smartlib.analysis_state_eligible(subject.review_state)
                 AND smartlib.analysis_state_eligible(object.review_state)
               GROUP BY relation.relation_id""",
            (self.projection_version, relation_id),
        ).fetchall()
        return [InternalGraphEdge.model_validate(row) for row in rows]


def _next_node(edge: InternalGraphEdge, current: UUID, direction: str) -> UUID | None:
    if direction in {"outgoing", "both"} and edge.subject_id == current:
        return edge.object_id
    if direction in {"incoming", "both"} and edge.object_id == current:
        return edge.subject_id
    return None


def _elapsed_ms(started: float) -> float:
    return (perf_counter() - started) * 1000
