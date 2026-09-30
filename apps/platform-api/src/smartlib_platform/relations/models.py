from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class EvidenceCreate(BaseModel):
    evidence_type: Literal[
        "business_record",
        "publication",
        "dataset",
        "contract",
        "manual_review",
        "model_output",
        "user_contribution",
    ]
    evidence_kind: str = Field(default="general", pattern=r"^[a-z][a-z0-9_.-]{1,127}$")
    fulltext_resource_id: UUID | None = None
    page_number: int | None = Field(default=None, ge=1)
    evidence_locator: dict[str, object] = Field(default_factory=dict)
    verification_state: Literal[
        "extracted", "needs_review", "confirmed", "rejected", "superseded"
    ] = "extracted"
    citation: str = Field(min_length=1, max_length=2000)
    excerpt: str | None = Field(default=None, max_length=5000)
    visibility: Literal["public", "campus", "restricted", "private"] = "restricted"
    license_tags: list[str] = Field(default_factory=list, max_length=50)
    metadata: dict[str, object] = Field(default_factory=dict)


class EvidenceView(EvidenceCreate):
    evidence_id: UUID
    object_id: UUID
    created_by: UUID
    created_at: datetime


class RelationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject_id: UUID
    predicate: str = Field(pattern=r"^[a-z][a-z0-9_.-]{1,127}$")
    object_id: UUID
    context_object_id: UUID | None = None
    fact_class: Literal[
        "business_fact",
        "literature_fact",
        "vendor_record",
        "statistical_analysis",
        "algorithmic_inference",
        "human_confirmed",
        "user_contribution",
    ]
    confidence: float | None = Field(default=None, ge=0, le=1)
    visibility: Literal["public", "campus", "restricted", "private"] = "restricted"
    license_tags: list[str] = Field(default_factory=list, max_length=50)
    review_state: Literal["pending", "approved", "rejected", "superseded"] = "pending"
    model_version: str | None = Field(default=None, max_length=200)
    attributes: dict[str, object] = Field(default_factory=dict)
    evidence_ids: list[UUID] = Field(default_factory=list, max_length=50)


class RelationView(RelationCreate):
    relation_id: UUID
    version: int
    created_by: UUID
    created_at: datetime
    updated_at: datetime
