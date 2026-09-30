from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class GovernanceSummary(BaseModel):
    visible_assets: int
    registered_sources: int
    license_grants: int
    effective_license_grants: int
    licenses_requiring_review: int
    open_quality_issues: int
    human_confirmation_issues: int
    active_contracts: int
    synthetic_assets: int
    generated_at: datetime


class LicenseGrantView(BaseModel):
    license_grant_id: UUID
    data_asset_id: UUID
    asset_name: str
    source_name: str
    allowed_content: list[str]
    allowed_purposes: list[str]
    prohibited_purposes: list[str]
    valid_from: datetime | None
    valid_to: datetime | None
    authorization_state: str
    effective_state: Literal["effective", "review_required", "denied", "expired", "not_yet_valid"]
    decision: Literal["allow", "deny"]
    synthetic: bool


class QualityIssueView(BaseModel):
    quality_issue_id: UUID
    data_asset_id: UUID
    asset_name: str
    title: str
    description: str | None
    severity: str
    issue_state: str
    requires_human_confirmation: bool
    quality_rule_code: str | None
    quality_rule_name: str | None
    run_state: str | None
    observed_value: float | None
    expected_value: float | None
    responsibility: str | None
    detected_at: datetime


class ReviewTaskCreate(BaseModel):
    issue_type: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,127}$")
    target_type: Literal["evidence", "relation", "knowledge_object", "publication_authorship"]
    target_id: UUID
    publication_id: UUID | None = None
    publication_authorship_id: UUID | None = None
    evidence_id: UUID | None = None
    relation_id: UUID | None = None
    object_id: UUID | None = None
    candidate_object_ids: list[UUID] = Field(default_factory=list, max_length=100)
    reason_code: str = Field(pattern=r"^[a-z][a-z0-9_.-]{1,127}$")
    description: str | None = Field(default=None, max_length=5000)
    machine_suggestion: dict[str, object] = Field(default_factory=dict)
    confidence: float | None = Field(default=None, ge=0, le=1)
    assigned_to: UUID | None = None

    @model_validator(mode="after")
    def target_reference_matches(self) -> ReviewTaskCreate:
        selected_target = {
            "evidence": self.evidence_id,
            "relation": self.relation_id,
            "knowledge_object": self.object_id,
            "publication_authorship": self.publication_authorship_id,
        }[self.target_type]
        if selected_target != self.target_id:
            raise ValueError("target_id must match the typed target reference")
        if self.target_type != "evidence" and self.evidence_id is not None:
            raise ValueError("evidence_id is only valid for an evidence target")
        if self.target_type != "relation" and self.relation_id is not None:
            raise ValueError("relation_id is only valid for a relation target")
        if self.target_type != "knowledge_object" and self.object_id is not None:
            raise ValueError("only the selected typed target reference may be set")
        return self


class ReviewTaskDecision(BaseModel):
    state: Literal["in_review", "resolved", "rejected", "cancelled"]
    decision: dict[str, object] = Field(default_factory=dict)


class ReviewTaskView(BaseModel):
    review_task_id: UUID
    issue_type: str
    target_type: str
    target_id: UUID
    publication_id: UUID | None
    publication_authorship_id: UUID | None
    evidence_id: UUID | None
    relation_id: UUID | None
    object_id: UUID | None
    candidate_object_ids: list[UUID]
    reason_code: str
    description: str | None
    machine_suggestion: dict[str, object]
    confidence: float | None
    state: str
    decision: dict[str, object]
    assigned_to: UUID | None
    reviewed_by: UUID | None
    reviewed_at: datetime | None
    created_by: UUID
    created_at: datetime
    updated_at: datetime


class GovernanceAuditEventView(BaseModel):
    event_id: UUID
    occurred_at: datetime
    action: str
    resource_type: str
    resource_id: str | None
    decision: str
    details: dict[str, object]


class GovernanceDashboard(BaseModel):
    summary: GovernanceSummary
    licenses: list[LicenseGrantView]
    quality_issues: list[QualityIssueView]
    audit_events: list[GovernanceAuditEventView]


class DataAssetTrace(BaseModel):
    data_asset_id: UUID
    asset_name: str
    asset_type: str
    lifecycle_state: str
    synthetic: bool
    dataset_version: str | None
    domain_name: str
    source_system_id: UUID
    source_name: str
    source_owner_department: str
    source_authorization_state: str
    latest_asset_version: int | None
    latest_schema_version: str | None
    contract_codes: list[str]
    steward_responsibilities: list[str]


class SourceReferenceTrace(BaseModel):
    source_reference_id: UUID
    source_system_id: UUID
    source_name: str
    external_id: str
    source_version: str | None
    observed_at: datetime
    raw_object_uri: str | None


class EvidenceTrace(BaseModel):
    evidence_id: UUID
    source_reference_id: UUID | None
    evidence_type: str
    evidence_kind: str
    fulltext_resource_id: UUID | None
    page_number: int | None
    evidence_locator: dict[str, object]
    verification_state: str
    citation: str
    excerpt: str | None
    created_at: datetime


class KnowledgeObjectProvenanceTrace(BaseModel):
    object_id: UUID
    object_type: str
    canonical_name: str
    object_version: int
    source_references: list[SourceReferenceTrace]
    evidence: list[EvidenceTrace]
