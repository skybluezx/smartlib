from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from smartlib_platform.foundation.types import ObjectType

Visibility = Literal["public", "campus", "restricted", "private"]
GraphDirection = Literal["outgoing", "incoming", "both"]


class GraphAccessContext(BaseModel):
    actor_id: UUID
    purpose: str
    trace_id: str


class NeighborhoodCommand(BaseModel):
    root_object_id: UUID
    direction: GraphDirection = "both"
    predicates: list[str] = Field(default_factory=list, max_length=20)
    object_types: list[ObjectType] = Field(default_factory=list, max_length=20)
    max_depth: int = Field(default=1, ge=1, le=3)
    limit: int = Field(default=50, ge=1, le=200)

    @model_validator(mode="after")
    def predicates_are_safe_identifiers(self) -> NeighborhoodCommand:
        if any(not predicate or len(predicate) > 128 for predicate in self.predicates):
            raise ValueError("predicates must be non-empty and at most 128 characters")
        return self


class PathCommand(BaseModel):
    start_object_id: UUID
    end_object_id: UUID
    direction: GraphDirection = "both"
    predicates: list[str] = Field(default_factory=list, max_length=20)
    max_depth: int = Field(default=4, ge=1, le=4)
    limit: int = Field(default=10, ge=1, le=20)


class GraphNode(BaseModel):
    object_id: UUID
    object_type: ObjectType
    canonical_name: str
    description: str | None
    object_version: int
    projection_version: str


class GraphEdge(BaseModel):
    relation_id: UUID
    subject_id: UUID
    object_id: UUID
    predicate: str
    fact_class: str
    confidence: float | None
    review_state: str
    attributes: dict[str, object] = Field(default_factory=dict)
    context_object_id: UUID | None = None
    evidence_ids: list[UUID]
    relation_version: int
    projection_version: str


class GraphPath(BaseModel):
    node_ids: list[UUID]
    relation_ids: list[UUID]


class NeighborhoodResult(BaseModel):
    root_object_id: UUID
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    backend: str
    projection_version: str
    truncated: bool
    took_ms: float


class PathResult(BaseModel):
    start_object_id: UUID
    end_object_id: UUID
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    paths: list[GraphPath]
    backend: str
    projection_version: str
    took_ms: float


class RelationExplanation(BaseModel):
    edge: GraphEdge
    subject: GraphNode
    object: GraphNode
    backend: str
    projection_version: str


class InternalGraphNode(GraphNode):
    visibility: Visibility
    created_by: UUID


class InternalGraphEdge(GraphEdge):
    visibility: Visibility
    created_by: UUID


class InternalGraphPath(BaseModel):
    node_ids: tuple[UUID, ...]
    relation_ids: tuple[UUID, ...]


class AdapterNeighborhoodResult(BaseModel):
    nodes: tuple[InternalGraphNode, ...]
    edges: tuple[InternalGraphEdge, ...]
    backend: str
    projection_version: str = "graph-projection-v1"
    truncated: bool = False
    took_ms: float


class AdapterPathResult(BaseModel):
    nodes: tuple[InternalGraphNode, ...]
    edges: tuple[InternalGraphEdge, ...]
    paths: tuple[InternalGraphPath, ...]
    backend: str
    projection_version: str = "graph-projection-v1"
    took_ms: float


class AdapterRelationExplanation(BaseModel):
    edge: InternalGraphEdge
    subject: InternalGraphNode
    object: InternalGraphNode
    backend: str
    projection_version: str = "graph-projection-v1"
