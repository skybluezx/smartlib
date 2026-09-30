from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from smartlib_platform.foundation.types import ObjectType

RetrievalMode = Literal["lexical", "semantic", "hybrid"]
Visibility = Literal["public", "campus", "restricted", "private"]


class SearchCommand(BaseModel):
    query_text: str = Field(min_length=1, max_length=500)
    object_types: list[ObjectType] = Field(default_factory=list, max_length=12)
    retrieval_mode: RetrievalMode = "lexical"
    page_size: int = Field(default=20, ge=1, le=100)
    cursor: str | None = Field(default=None, max_length=1000)


class SearchHit(BaseModel):
    object_id: UUID
    object_type: ObjectType
    canonical_name: str
    description: str | None
    score: float
    recall_channels: list[Literal["lexical", "semantic"]]
    object_version: int
    projection_version: str
    source_updated_at: datetime
    evidence_ids: list[UUID] = Field(default_factory=list)


class SearchFacets(BaseModel):
    object_types: dict[str, int] = Field(default_factory=dict)


class SearchResult(BaseModel):
    query_text: str
    retrieval_mode: RetrievalMode
    hits: list[SearchHit]
    facets: SearchFacets
    next_cursor: str | None
    backend: Literal["postgres", "opensearch"]
    took_ms: float = Field(ge=0)
    warnings: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class SearchAccessContext:
    actor_id: UUID
    purpose: str
    trace_id: str


@dataclass(frozen=True)
class InternalSearchHit:
    object_id: UUID
    object_type: ObjectType
    canonical_name: str
    description: str | None
    visibility: Visibility
    created_by: UUID
    score: float
    recall_channels: tuple[Literal["lexical", "semantic"], ...]
    object_version: int
    projection_version: str
    source_updated_at: datetime


@dataclass(frozen=True)
class AdapterSearchResult:
    hits: tuple[InternalSearchHit, ...]
    object_type_facets: dict[str, int]
    next_cursor: str | None
    backend: Literal["postgres", "opensearch"]
    took_ms: float
    warnings: tuple[str, ...] = ()
