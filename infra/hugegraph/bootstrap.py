import base64
import json
import os
import urllib.error
import urllib.request

BASE_URL = os.environ.get("SMARTLIB_HUGEGRAPH_URL", "http://hugegraph:8080").rstrip("/")
GRAPH = os.environ.get("SMARTLIB_HUGEGRAPH_GRAPH", "hugegraph")
USER = os.environ.get("SMARTLIB_HUGEGRAPH_USER", "admin")
PASSWORD = os.environ["SMARTLIB_HUGEGRAPH_PASSWORD"]
SCHEMA_URL = f"{BASE_URL}/graphspaces/DEFAULT/graphs/{GRAPH}/schema"
AUTHORIZATION = "Basic " + base64.b64encode(f"{USER}:{PASSWORD}".encode()).decode()


def request(method: str, path: str, body: dict[str, object] | None = None) -> object:
    data = None if body is None else json.dumps(body).encode()
    operation = urllib.request.Request(
        f"{SCHEMA_URL}/{path}",
        data=data,
        method=method,
        headers={"Authorization": AUTHORIZATION, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(operation, timeout=20) as response:
        payload = response.read()
        return None if not payload else json.loads(payload)


def ensure(path: str, name: str, body: dict[str, object]) -> None:
    try:
        request("GET", f"{path}/{name}")
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
        request("POST", path, body)


def main() -> None:
    property_keys = {
        "object_id": ("TEXT", "SINGLE"),
        "object_type": ("TEXT", "SINGLE"),
        "canonical_name": ("TEXT", "SINGLE"),
        "description": ("TEXT", "SINGLE"),
        "visibility": ("TEXT", "SINGLE"),
        "access_scope": ("TEXT", "SINGLE"),
        "created_by": ("TEXT", "SINGLE"),
        "object_version": ("INT", "SINGLE"),
        "projection_version": ("TEXT", "SINGLE"),
        "relation_id": ("TEXT", "SINGLE"),
        "subject_id": ("TEXT", "SINGLE"),
        "predicate": ("TEXT", "SINGLE"),
        "fact_class": ("TEXT", "SINGLE"),
        "confidence": ("DOUBLE", "SINGLE"),
        "review_state": ("TEXT", "SINGLE"),
        "relation_version": ("INT", "SINGLE"),
        "evidence_ids_json": ("TEXT", "SINGLE"),
        "evidence_visibilities_json": ("TEXT", "SINGLE"),
        "evidence_created_by_json": ("TEXT", "SINGLE"),
        "relation_attributes_json": ("TEXT", "SINGLE"),
        "context_object_id": ("TEXT", "SINGLE"),
    }
    for name, (data_type, cardinality) in property_keys.items():
        ensure(
            "propertykeys",
            name,
            {"name": name, "data_type": data_type, "cardinality": cardinality},
        )

    node_properties = [
        "object_id",
        "object_type",
        "canonical_name",
        "description",
        "visibility",
        "access_scope",
        "created_by",
        "object_version",
        "projection_version",
    ]
    ensure(
        "vertexlabels",
        "knowledge_object",
        {
            "name": "knowledge_object",
            "id_strategy": "PRIMARY_KEY",
            "properties": node_properties,
            "primary_keys": ["object_id"],
            "nullable_keys": ["description"],
            "enable_label_index": True,
        },
    )

    edge_properties = [
        "relation_id",
        "subject_id",
        "object_id",
        "predicate",
        "fact_class",
        "confidence",
        "review_state",
        "visibility",
        "access_scope",
        "created_by",
        "relation_version",
        "projection_version",
        "evidence_ids_json",
        "evidence_visibilities_json",
        "evidence_created_by_json",
        "relation_attributes_json",
        "context_object_id",
    ]
    ensure(
        "edgelabels",
        "relates",
        {
            "name": "relates",
            "source_label": "knowledge_object",
            "target_label": "knowledge_object",
            "frequency": "MULTIPLE",
            "properties": edge_properties,
            "sort_keys": ["relation_id"],
            "nullable_keys": ["confidence", "context_object_id"],
            "enable_label_index": True,
        },
    )

    indexes = {
        "knowledge_object_by_type": ("VERTEX_LABEL", "knowledge_object", ["object_type"]),
        "knowledge_object_by_access": (
            "VERTEX_LABEL",
            "knowledge_object",
            ["access_scope"],
        ),
        "relation_by_id": ("EDGE_LABEL", "relates", ["relation_id"]),
        "relation_by_predicate": ("EDGE_LABEL", "relates", ["predicate"]),
        "relation_by_access": ("EDGE_LABEL", "relates", ["access_scope"]),
    }
    for name, (base_type, base_value, fields) in indexes.items():
        ensure(
            "indexlabels",
            name,
            {
                "name": name,
                "base_type": base_type,
                "base_value": base_value,
                "index_type": "SECONDARY",
                "fields": fields,
            },
        )
    print("SMARTLIB_HUGEGRAPH_BOOTSTRAP_OK")


if __name__ == "__main__":
    main()
