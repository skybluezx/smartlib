import json
from time import perf_counter
from typing import Any, cast
from uuid import UUID

import httpx

from .errors import GraphBackendUnavailable
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


class CustomGraphQueryRejected(RuntimeError):
    pass


class HugeGraphAdapter:
    backend_name = "hugegraph"
    projection_version = "graph-projection-v1"

    def __init__(self, url: str, user: str, password: str, graph: str = "hugegraph") -> None:
        base = url.rstrip("/")
        self.endpoint = f"{base}/graphspaces/DEFAULT/graphs/{graph}/cypher"
        self.auth = (user, password)

    def neighborhood(
        self, command: NeighborhoodCommand, access: GraphAccessContext
    ) -> AdapterNeighborhoodResult:
        started = perf_counter()
        rows: list[dict[str, Any]] = []
        for depth in range(1, command.max_depth + 1):
            pattern, node_vars, edge_vars = _fixed_path(command.direction, depth)
            clauses = _fixed_path_clauses(
                node_vars,
                edge_vars,
                access.actor_id,
                command.predicates,
                command.object_types,
            )
            clauses.insert(0, f"root.object_id = {_literal(str(command.root_object_id))}")
            statement = f"""MATCH {pattern}
WHERE {" AND ".join(clauses)}
RETURN [{", ".join(f"properties({node})" for node in node_vars)}] AS node_docs,
       [{", ".join(f"properties({edge})" for edge in edge_vars)}] AS edge_docs
LIMIT {command.limit + 1}"""
            rows.extend(self._query(statement))
        nodes, edges, _ = _materialize_rows(rows, access.actor_id)
        truncated = len(edges) > command.limit
        if truncated:
            edges = dict(list(edges.items())[: command.limit])
            used_node_ids = {command.root_object_id} | {
                endpoint for edge in edges.values() for endpoint in (edge.subject_id, edge.object_id)
            }
            nodes = {node_id: node for node_id, node in nodes.items() if node_id in used_node_ids}
        return AdapterNeighborhoodResult(
            nodes=tuple(nodes.values()),
            edges=tuple(edges.values()),
            backend=self.backend_name,
            projection_version=self.projection_version,
            truncated=truncated,
            took_ms=_elapsed_ms(started),
        )

    def find_paths(self, command: PathCommand, access: GraphAccessContext) -> AdapterPathResult:
        started = perf_counter()
        rows: list[dict[str, Any]] = []
        for depth in range(1, command.max_depth + 1):
            remaining = command.limit - len(rows)
            if remaining <= 0:
                break
            pattern, node_vars, edge_vars = _fixed_path(command.direction, depth)
            clauses = _fixed_path_clauses(node_vars, edge_vars, access.actor_id, command.predicates, [])
            clauses.insert(0, f"root.object_id = {_literal(str(command.start_object_id))}")
            clauses.insert(1, f"n{depth}.object_id = {_literal(str(command.end_object_id))}")
            statement = f"""MATCH {pattern}
WHERE {" AND ".join(clauses)}
RETURN [{", ".join(f"properties({node})" for node in node_vars)}] AS node_docs,
       [{", ".join(f"properties({edge})" for edge in edge_vars)}] AS edge_docs,
       [{", ".join(f"{node}.object_id" for node in node_vars)}] AS node_ids,
       [{", ".join(f"{edge}.relation_id" for edge in edge_vars)}] AS relation_ids
LIMIT {remaining}"""
            rows.extend(self._query(statement))
        nodes, edges, paths = _materialize_rows(rows, access.actor_id)
        return AdapterPathResult(
            nodes=tuple(nodes.values()),
            edges=tuple(edges.values()),
            paths=tuple(paths),
            backend=self.backend_name,
            projection_version=self.projection_version,
            took_ms=_elapsed_ms(started),
        )

    def explain_relation(
        self, relation_id: UUID, access: GraphAccessContext
    ) -> AdapterRelationExplanation | None:
        scopes = _literal(["public", str(access.actor_id)])
        statement = f"""MATCH (subject:knowledge_object)-[relation:relates]->(object:knowledge_object)
WHERE relation.relation_id = {_literal(str(relation_id))}
  AND subject.access_scope IN {scopes}
  AND relation.access_scope IN {scopes}
  AND object.access_scope IN {scopes}
RETURN properties(subject) AS subject,
       properties(relation) AS relation,
       properties(object) AS object
LIMIT 1"""
        rows = self._query(statement)
        if not rows:
            return None
        row = rows[0]
        return AdapterRelationExplanation(
            subject=_node(cast(dict[str, Any], row["subject"])),
            edge=_edge(cast(dict[str, Any], row["relation"]), access.actor_id),
            object=_node(cast(dict[str, Any], row["object"])),
            backend=self.backend_name,
            projection_version=self.projection_version,
        )

    def custom_publication_scope(
        self,
        statement: str,
        access: GraphAccessContext,
        *,
        limit: int = 5000,
    ) -> tuple[list[UUID], bool, float]:
        started = perf_counter()
        secured_statement = _secure_custom_scope_statement(statement, access.actor_id, limit)
        rows = self._query(secured_statement, timeout=5, custom_scope=True)
        values: list[UUID] = []
        for row in rows:
            value = row.get("publication_id")
            if value is None:
                continue
            try:
                values.append(UUID(str(value)))
            except ValueError as exc:
                raise ValueError("图查询返回了无效的 publication_id") from exc
        unique_values = list(dict.fromkeys(values))
        return unique_values[:limit], len(unique_values) > limit, _elapsed_ms(started)

    def _query(
        self, statement: str, *, timeout: float = 10, custom_scope: bool = False
    ) -> list[dict[str, Any]]:
        try:
            response = httpx.get(
                self.endpoint,
                auth=self.auth,
                params={"cypher": statement},
                timeout=timeout,
            )
            if custom_scope and response.status_code >= 400:
                raise CustomGraphQueryRejected("当前 HugeGraph 无法解析这条 Cypher 查询")
            response.raise_for_status()
            payload = cast(dict[str, Any], response.json())
            status = cast(dict[str, Any], payload.get("status", {}))
            if status.get("code") not in {None, 200}:
                if custom_scope:
                    raise CustomGraphQueryRejected("当前 HugeGraph 无法执行这条 Cypher 查询")
                raise ValueError("HugeGraph Cypher query was rejected")
            result = cast(dict[str, Any], payload.get("result", {}))
            rows = result.get("data", [])
            if not isinstance(rows, list):
                raise TypeError("HugeGraph Cypher result data must be a list")
            return cast(list[dict[str, Any]], rows)
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise GraphBackendUnavailable("HugeGraph graph projection unavailable") from exc


def _secure_custom_scope_statement(statement: str, actor_id: UUID, limit: int) -> str:
    import re

    query = statement.strip()
    if query.endswith(";"):
        query = query[:-1].rstrip()
    if not query or len(query) > 4000:
        raise ValueError("查询语句长度必须在 1 到 4000 个字符之间")
    if ";" in query or any(marker in query for marker in ("//", "/*", "*/", "--")):
        raise ValueError("自定义范围只允许一条不含注释的查询语句")
    banned = re.compile(
        r"\b(?:CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP|ALTER|CALL|LOAD|UNION|FOREACH|"
        r"YIELD|PROFILE|EXPLAIN|OPTIONAL|WITH|UNWIND|SKIP|LIMIT|ORDER)\b",
        re.IGNORECASE,
    )
    if banned.search(query) or "*" in query:
        raise ValueError("自定义范围只支持固定路径的只读 MATCH 查询")
    if len(re.findall(r"\bMATCH\b", query, flags=re.IGNORECASE)) != 1:
        raise ValueError("自定义范围必须且只能包含一个 MATCH 子句")
    return_match = re.search(
        r"\bRETURN\s+(?:DISTINCT\s+)?publication\.object_id\s+AS\s+publication_id\s*$",
        query,
        flags=re.IGNORECASE,
    )
    if return_match is None:
        raise ValueError(
            "查询必须以 RETURN DISTINCT publication.object_id AS publication_id 结束"
        )
    prefix = query[: return_match.start()].rstrip()
    node_patterns = re.findall(r"\(\s*([A-Za-z_]\w*)\s*:\s*knowledge_object\b", prefix)
    edge_patterns = re.findall(r"\[\s*([A-Za-z_]\w*)\s*:\s*relates\b", prefix)
    if "publication" not in node_patterns:
        raise ValueError("查询必须声明 (publication:knowledge_object) 论文节点")
    all_node_variables = re.findall(r"\(\s*([A-Za-z_]\w*)", prefix)
    all_edge_variables = re.findall(r"\[\s*([A-Za-z_]\w*)", prefix)
    if set(all_node_variables) != set(node_patterns) or set(all_edge_variables) != set(edge_patterns):
        raise ValueError("节点必须使用 knowledge_object 标签; 关系必须使用 relates 标签")
    scopes = _literal(["public", str(actor_id)])
    access_clauses = [
        *(f"{variable}.access_scope IN {scopes}" for variable in dict.fromkeys(node_patterns)),
        *(f"{variable}.access_scope IN {scopes}" for variable in dict.fromkeys(edge_patterns)),
    ]
    connector = " AND " if re.search(r"\bWHERE\b", prefix, flags=re.IGNORECASE) else " WHERE "
    return (
        f"{prefix}{connector}{' AND '.join(access_clauses)}\n"
        "RETURN DISTINCT publication.object_id AS publication_id\n"
        f"LIMIT {limit + 1}"
    )


def _fixed_path(direction: str, depth: int) -> tuple[str, list[str], list[str]]:
    node_vars = ["root", *(f"n{index}" for index in range(1, depth + 1))]
    edge_vars = [f"r{index}" for index in range(1, depth + 1)]
    pattern = "(root:knowledge_object)"
    for index in range(1, depth + 1):
        edge = f"[{edge_vars[index - 1]}:relates]"
        node = f"({node_vars[index]}:knowledge_object)"
        if direction == "outgoing":
            pattern += f"-{edge}->{node}"
        elif direction == "incoming":
            pattern += f"<-{edge}-{node}"
        else:
            pattern += f"-{edge}-{node}"
    return pattern, node_vars, edge_vars


def _fixed_path_clauses(
    node_vars: list[str],
    edge_vars: list[str],
    actor_id: UUID,
    predicates: list[str],
    object_types: list[str],
) -> list[str]:
    scopes = _literal(["public", str(actor_id)])
    clauses = [f"{variable}.access_scope IN {scopes}" for variable in node_vars]
    clauses.extend(f"{variable}.access_scope IN {scopes}" for variable in edge_vars)
    if predicates:
        clauses.extend(f"{variable}.predicate IN {_literal(predicates)}" for variable in edge_vars)
    if object_types:
        clauses.extend(f"{variable}.object_type IN {_literal(object_types)}" for variable in node_vars[1:])
    clauses.extend(
        f"{left} <> {right}" for index, left in enumerate(node_vars) for right in node_vars[index + 1 :]
    )
    return clauses


def _literal(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _materialize_rows(
    rows: list[dict[str, Any]], actor_id: UUID
) -> tuple[dict[UUID, InternalGraphNode], dict[UUID, InternalGraphEdge], list[InternalGraphPath]]:
    nodes: dict[UUID, InternalGraphNode] = {}
    edges: dict[UUID, InternalGraphEdge] = {}
    paths: list[InternalGraphPath] = []
    for row in rows:
        for document in cast(list[dict[str, Any]], row.get("node_docs", [])):
            node = _node(document)
            nodes[node.object_id] = node
        for document in cast(list[dict[str, Any]], row.get("edge_docs", [])):
            edge = _edge(document, actor_id)
            edges[edge.relation_id] = edge
        if "node_ids" in row and "relation_ids" in row:
            paths.append(
                InternalGraphPath(
                    node_ids=tuple(UUID(value) for value in cast(list[str], row["node_ids"])),
                    relation_ids=tuple(UUID(value) for value in cast(list[str], row["relation_ids"])),
                )
            )
    return nodes, edges, paths


def _node(document: dict[str, Any]) -> InternalGraphNode:
    # HugeGraph omits properties whose source value is null.
    # Keep the API's nullable field explicit without mutating the response document.
    normalized = dict(document)
    normalized.setdefault("description", None)
    return InternalGraphNode.model_validate(normalized)


def _edge(document: dict[str, Any], actor_id: UUID) -> InternalGraphEdge:
    normalized = dict(document)
    normalized.setdefault("confidence", None)
    for key in ("context_object_id",):
        normalized[key] = normalized.get(key) or None
    normalized["attributes"] = json.loads(str(normalized.pop("relation_attributes_json", "{}")))
    evidence_ids = json.loads(str(normalized.pop("evidence_ids_json", "[]")))
    evidence_visibilities = json.loads(str(normalized.pop("evidence_visibilities_json", "[]")))
    evidence_created_by = json.loads(str(normalized.pop("evidence_created_by_json", "[]")))
    normalized["evidence_ids"] = [
        evidence_id
        for evidence_id, visibility, created_by in zip(
            evidence_ids, evidence_visibilities, evidence_created_by, strict=True
        )
        if visibility == "public" or created_by == str(actor_id)
    ]
    return InternalGraphEdge.model_validate(normalized)


def _elapsed_ms(started: float) -> float:
    return (perf_counter() - started) * 1000
