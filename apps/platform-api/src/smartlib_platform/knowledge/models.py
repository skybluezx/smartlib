from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from smartlib_platform.foundation.types import ObjectType


class KnowledgeObjectCreate(BaseModel):
    object_type: ObjectType
    canonical_name: str = Field(min_length=1, max_length=500)
    description: str | None = None
    visibility: Literal["public", "campus", "restricted", "private"] = "campus"
    attributes: dict[str, object] = Field(default_factory=dict)


class KnowledgeObjectHierarchyNode(BaseModel):
    object_id: UUID
    object_type: ObjectType
    canonical_name: str


class KnowledgeObjectView(KnowledgeObjectCreate):
    object_id: UUID
    quality_state: str
    review_state: str
    version: int
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    publication_year: int | None = None
    hierarchy_path: list[KnowledgeObjectHierarchyNode] = Field(default_factory=list)


class KnowledgeObjectPage(BaseModel):
    items: list[KnowledgeObjectView]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)


class OrganizationHierarchyScope(BaseModel):
    object_id: UUID
    canonical_name: str
    descendant_count: int = Field(ge=1)


class OrganizationHierarchyOptions(BaseModel):
    scopes: list[OrganizationHierarchyScope] = Field(default_factory=list)
    levels: list[int] = Field(default_factory=list)


class ProjectKindOption(BaseModel):
    object_id: UUID
    canonical_name: str
    category_label: str | None = None
    project_count: int = Field(ge=0)


class ProjectKindOptions(BaseModel):
    items: list[ProjectKindOption] = Field(default_factory=list)


class KnowledgeObjectIdentifierView(BaseModel):
    identifier_type: str
    value: str
    is_primary: bool
    verification_status: str


class KnowledgeObjectContributorView(BaseModel):
    order: int = Field(ge=1)
    name: str
    orcid: str | None = None
    affiliation: str | None = None
    affiliations: list[str] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)
    person_object_id: UUID | None = None
    verification_status: str
    role_source: str = "metadata"
    role_evidence: dict[str, object] = Field(default_factory=dict)


class KnowledgeObjectResourceView(BaseModel):
    resource_id: UUID
    file_name: str
    mime_type: str
    resource_role: Literal["article", "correction", "supplementary"]
    size_bytes: int | None = None
    extraction_state: str
    license_tags: list[str] = Field(default_factory=list)


class InstitutionAssociatedScholarView(BaseModel):
    object_id: UUID
    canonical_name: str
    output_count: int = Field(ge=0)


class InstitutionAssociatedOutputView(BaseModel):
    object_id: UUID
    object_type: Literal["publication", "project"]
    canonical_name: str
    year: int | None = None
    scholar_count: int = Field(ge=1)


class InstitutionAssociationSummary(BaseModel):
    scholar_count: int = Field(ge=0)
    output_count: int = Field(ge=0)
    scholars: list[InstitutionAssociatedScholarView] = Field(default_factory=list)
    outputs: list[InstitutionAssociatedOutputView] = Field(default_factory=list)
    truncated: bool = False
    metric_scope: str = "institution_descendants_to_approved_scholars_to_approved_outputs"


class PublicationJournalMetricDetail(BaseModel):
    record_id: UUID
    metric_system: str
    metric_year: int
    release_id: UUID
    release_label: str
    impact_factor: float | None = None
    impact_factor_is_upper_bound: bool = False
    quartile: str | None = None
    categories: list[str] = Field(default_factory=list)
    source_row_number: int


class KnowledgeObjectDetailView(BaseModel):
    object: KnowledgeObjectView
    type_details: dict[str, object] = Field(default_factory=dict)
    identifiers: list[KnowledgeObjectIdentifierView] = Field(default_factory=list)
    contributors: list[KnowledgeObjectContributorView] = Field(default_factory=list)
    resources: list[KnowledgeObjectResourceView] = Field(default_factory=list)
    institution_associations: InstitutionAssociationSummary | None = None
    journal_metrics: list[PublicationJournalMetricDetail] = Field(default_factory=list)
