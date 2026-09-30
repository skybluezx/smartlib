from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class ScholarMetrics(BaseModel):
    publications: int = Field(ge=0)
    projects: int = Field(ge=0)
    collaborators: int = Field(ge=0)


class ScholarSummary(BaseModel):
    object_id: UUID
    scholar_id: str
    canonical_name: str
    initials: str
    title: str | None
    department: str | None
    authoritative_organizations: list[str] = Field(default_factory=list)
    output_organizations: list[str] = Field(default_factory=list)
    discipline: str | None
    primary_direction: str | None
    metrics: ScholarMetrics
    synthetic: bool
    dataset_version: str | None
    object_version: int
    updated_at: datetime


class ScholarRelatedItem(BaseModel):
    object_id: UUID
    object_type: Literal["publication", "project", "person"]
    canonical_name: str
    description: str | None
    relation_id: UUID
    predicate: str
    fact_class: str
    confidence: float | None
    review_state: str
    evidence_count: int = Field(ge=0)
    object_version: int
    year: int | None = None
    item_type: str | None = None


class ScholarDirection(BaseModel):
    object_id: UUID
    canonical_name: str
    relation_id: UUID
    fact_class: str
    confidence: float | None
    review_state: str
    evidence_count: int = Field(ge=0)


class AffiliationEvidence(BaseModel):
    evidence_id: UUID
    citation: str
    excerpt: str | None = None
    page_number: int | None = None
    fulltext_resource_id: UUID | None = None
    source_name: str | None = None
    source_reference_id: UUID | None = None
    observed_at: str | None = None


class ScholarAffiliation(BaseModel):
    relation_id: UUID
    organization_id: UUID
    organization_name: str
    organization_level: int | None = None
    parent_organization_ids: list[UUID] = Field(default_factory=list)
    category: Literal["authoritative", "output"]
    context_object_id: UUID | None = None
    context_title: str | None = None
    raw_affiliation: str | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    is_current: bool
    evidence: list[AffiliationEvidence] = Field(default_factory=list)


class ScholarOverviewPaper(BaseModel):
    object_id: UUID
    canonical_name: str
    description: str | None
    review_state: str
    relation_id: UUID
    year: int | None
    doi: str | None
    pmid: str | None
    pmcid: str | None
    evidence_count: int


class ScholarOverview(BaseModel):
    counts: dict[str, int]
    papers: list[ScholarOverviewPaper]
    scope: str
    truncated: bool


class ScholarProfile(BaseModel):
    summary: ScholarSummary
    description: str | None
    profile_kind: Literal["fact_profile"] = "fact_profile"
    disciplines: list[str]
    research_directions: list[ScholarDirection]
    representative_publications: list[ScholarRelatedItem]
    projects: list[ScholarRelatedItem]
    collaborators: list[ScholarRelatedItem]
    affiliations: list[ScholarAffiliation] = Field(default_factory=list)
    metric_scope: str = "current_visible_analysis_eligible_relations"
    overview: ScholarOverview | None = None


class ScholarEvidenceItem(BaseModel):
    evidence_id: UUID
    object_id: UUID | None
    evidence_type: str
    citation: str
    excerpt: str | None
    source_reference_id: UUID | None
    source_name: str | None
    source_version: str | None
    observed_at: datetime | None
    dataset_version: str | None
    synthetic: bool
    relation_id: UUID | None
    predicate: str | None
    fact_class: str | None
    confidence: float | None
    review_state: str | None


class ScholarEvidenceBundle(BaseModel):
    scholar_id: str
    object_version: int
    items: list[ScholarEvidenceItem]
