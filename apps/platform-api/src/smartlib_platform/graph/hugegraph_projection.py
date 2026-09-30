import json
from typing import Any, cast
from urllib.parse import quote

import httpx

from .errors import GraphBackendUnavailable


class HugeGraphProjectionWriter:
    def __init__(self, url: str, user: str, password: str, graph: str = "hugegraph") -> None:
        base = url.rstrip("/")
        self.base_url = f"{base}/graphspaces/DEFAULT/graphs/{graph}/graph"
        self.auth = (user, password)
        self._node_cache: dict[str, tuple[object, int]] = {}
        self._client = httpx.Client(timeout=10)

    def deliver(self, delivery: dict[str, Any]) -> None:
        operation = delivery.get("operation")
        entity_kind = delivery.get("entity_kind")
        if entity_kind == "node" and operation == "upsert":
            self._upsert_node(cast(dict[str, Any], delivery["document"]))
            return
        if entity_kind == "node" and operation == "delete":
            self._delete_node(str(delivery["object_id"]))
            return
        if entity_kind == "relation" and operation == "upsert":
            for node in cast(list[dict[str, Any]], delivery["nodes"]):
                self._upsert_node(node)
            self._upsert_relation(cast(dict[str, Any], delivery["document"]))
            return
        if entity_kind == "relation" and operation == "delete":
            self._delete_relation(str(delivery["relation_id"]))
            return
        raise ValueError("unsupported graph projection delivery")

    def _upsert_node(self, document: dict[str, Any]) -> object:
        object_id = str(document["object_id"])
        object_version = int(document["object_version"])
        cached = self._node_cache.get(object_id)
        if cached is not None and cached[1] >= object_version:
            return cached[0]
        properties: dict[str, object] = {
            "object_id": object_id,
            "object_type": str(document["object_type"]),
            "canonical_name": str(document["canonical_name"]),
            "visibility": str(document["visibility"]),
            "access_scope": _access_scope(document),
            "created_by": str(document["created_by"]),
            "object_version": object_version,
            "projection_version": str(document["projection_version"]),
        }
        if document.get("description") is not None:
            properties["description"] = str(document["description"])
        existing = self._find_one("vertices", "object_id", object_id)
        if existing is None:
            created = self._request(
                "POST",
                "vertices",
                json_body={"label": "knowledge_object", "properties": properties},
            )
            vertex_id = cast(dict[str, Any], created)["id"]
            self._node_cache[object_id] = (vertex_id, object_version)
            return vertex_id
        vertex_id = existing["id"]
        update_properties = dict(properties)
        update_properties.pop("object_id")
        self._request(
            "PUT",
            f"vertices/{_path_id(vertex_id)}",
            params={"action": "append"},
            json_body={"label": "knowledge_object", "properties": update_properties},
        )
        if document.get("description") is None:
            self._request(
                "PUT",
                f"vertices/{_path_id(vertex_id)}",
                params={"action": "eliminate"},
                json_body={
                    "label": "knowledge_object",
                    "properties": {"description": ""},
                },
            )
        self._node_cache[object_id] = (vertex_id, object_version)
        return vertex_id

    def _delete_node(self, object_id: str) -> None:
        existing = self._find_one("vertices", "object_id", object_id)
        if existing is not None:
            self._request(
                "DELETE",
                f"vertices/{_path_id(existing['id'])}",
                params={"label": "knowledge_object"},
            )
        self._node_cache.pop(object_id, None)

    def _upsert_relation(self, document: dict[str, Any]) -> None:
        relation_id = str(document["relation_id"])
        subject = self._find_required_node(str(document["subject_id"]))
        object_node = self._find_required_node(str(document["object_id"]))
        properties: dict[str, object] = {
            "relation_id": relation_id,
            "subject_id": str(document["subject_id"]),
            "object_id": str(document["object_id"]),
            "predicate": str(document["predicate"]),
            "fact_class": str(document["fact_class"]),
            "review_state": str(document["review_state"]),
            "visibility": str(document["visibility"]),
            "access_scope": _access_scope(document),
            "created_by": str(document["created_by"]),
            "relation_version": int(document["relation_version"]),
            "projection_version": str(document["projection_version"]),
            "relation_attributes_json": json.dumps(document.get("attributes", {}), ensure_ascii=False),
            "context_object_id": str(document.get("context_object_id") or ""),
            "evidence_ids_json": json.dumps(document.get("evidence_ids_all", [])),
            "evidence_visibilities_json": json.dumps(document.get("evidence_visibilities", [])),
            "evidence_created_by_json": json.dumps(document.get("evidence_created_by", [])),
        }
        if document.get("confidence") is not None:
            properties["confidence"] = float(document["confidence"])
        existing = self._find_one("edges", "relation_id", relation_id)
        if existing is not None and (
            existing.get("outV") != subject["id"] or existing.get("inV") != object_node["id"]
        ):
            self._request("DELETE", f"edges/{_edge_path_id(existing['id'])}")
            existing = None
        if existing is None:
            self._request(
                "POST",
                "edges",
                json_body={
                    "label": "relates",
                    "outV": subject["id"],
                    "inV": object_node["id"],
                    "outVLabel": "knowledge_object",
                    "inVLabel": "knowledge_object",
                    "properties": properties,
                },
            )
            return
        edge_id = existing["id"]
        update_properties = dict(properties)
        update_properties.pop("relation_id")
        self._request(
            "PUT",
            f"edges/{_edge_path_id(edge_id)}",
            params={"action": "append"},
            json_body={"properties": update_properties},
        )
        if document.get("confidence") is None:
            self._request(
                "PUT",
                f"edges/{_edge_path_id(edge_id)}",
                params={"action": "eliminate"},
                json_body={"properties": {"confidence": 0.0}},
            )

    def _delete_relation(self, relation_id: str) -> None:
        existing = self._find_one("edges", "relation_id", relation_id)
        if existing is not None:
            self._request("DELETE", f"edges/{_edge_path_id(existing['id'])}")

    def _find_required_node(self, object_id: str) -> dict[str, Any]:
        cached = self._node_cache.get(object_id)
        if cached is not None:
            return {"id": cached[0]}
        node = self._find_one("vertices", "object_id", object_id)
        if node is None:
            raise GraphBackendUnavailable(f"HugeGraph node missing for object {object_id}")
        return node

    def _find_one(self, collection: str, key: str, value: str) -> dict[str, Any] | None:
        payload = cast(
            dict[str, Any],
            self._request(
                "GET",
                collection,
                params={
                    "label": "knowledge_object" if collection == "vertices" else "relates",
                    "properties": json.dumps({key: value}, separators=(",", ":")),
                    "limit": 2,
                },
            ),
        )
        matches = cast(list[dict[str, Any]], payload.get(collection, []))
        if len(matches) > 1:
            raise GraphBackendUnavailable(f"HugeGraph duplicate {key}: {value}")
        return matches[0] if matches else None

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str | int | float | bool | None] | None = None,
        json_body: dict[str, object] | None = None,
    ) -> object:
        try:
            response = self._client.request(
                method,
                f"{self.base_url}/{path}",
                auth=self.auth,
                params=params,
                json=json_body,
            )
            response.raise_for_status()
            return None if not response.content else response.json()
        except (httpx.HTTPError, TypeError, ValueError) as exc:
            raise GraphBackendUnavailable("HugeGraph projection unavailable") from exc


def _access_scope(document: dict[str, Any]) -> str:
    return "public" if document.get("visibility") == "public" else str(document["created_by"])


def _path_id(value: object) -> str:
    return quote(json.dumps(value, ensure_ascii=False), safe="")


def _edge_path_id(value: object) -> str:
    # HugeGraph vertex IDs use JSON literals in the path, while composite edge
    # IDs may be returned either as plain strings or as JSON string literals.
    # The REST edge path expects the composite value without JSON quote marks.
    raw = str(value)
    if raw.startswith('"') and raw.endswith('"'):
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError:
            decoded = raw
        if isinstance(decoded, str):
            raw = decoded
    return quote(raw, safe="")
