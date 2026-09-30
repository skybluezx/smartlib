from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class KnowledgeHubSession(BaseModel):
    actor_id: UUID
    permissions: list[str]


class ServiceStatus(BaseModel):
    service: Literal["postgresql", "hugegraph", "opensearch"]
    state: Literal["available", "unavailable"]
    purpose: str
    active_backend: bool
    detail: str


class ImportBatchSummary(BaseModel):
    batch_id: UUID
    dataset_version: str
    batch_state: str
    total_items: int
    completed_items: int
    manual_review_items: int
    rejected_items: int
    updated_at: datetime


class KnowledgeHubOverview(BaseModel):
    entity_counts: dict[str, int]
    registered_sources: int
    pending_verifications: int
    conflict_fields: int
    verification_states: dict[str, int]
    verification_layers: dict[str, dict[str, int]] = Field(default_factory=dict)
    latest_import: ImportBatchSummary | None
    unpublished_events: int
    services: list[ServiceStatus]
    generated_at: datetime


class PublicationImportRecordInput(BaseModel):
    title: str = Field(min_length=1, max_length=2000)
    journal_name: str | None = Field(default=None, max_length=1000)
    publication_year: int | None = Field(default=None, ge=1500, le=2200)
    doi: str | None = Field(default=None, max_length=500)
    pmid: str | None = Field(default=None, max_length=100)
    pmcid: str | None = Field(default=None, max_length=100)
    authors: list[str] = Field(default_factory=list)
    awardee_name: str | None = Field(default=None, max_length=500)
    representative_work_number: str | None = Field(default=None, max_length=200)
    metadata: dict[str, object] = Field(default_factory=dict)


class PublicationImportCreate(BaseModel):
    source_label: str = Field(min_length=1, max_length=500)
    source_uri: str | None = Field(default=None, max_length=2000)
    record: PublicationImportRecordInput


class PublicationImportItemResult(BaseModel):
    record_id: UUID
    source_row_number: int
    title: str
    verification_state: str
    automatic_verification_eligible: bool
    eligibility_reasons: list[str] = Field(default_factory=list)


class PublicationImportResult(BaseModel):
    batch_id: UUID
    dataset_version: str
    source_label: str
    accepted_count: int
    automatic_eligible_count: int
    manual_review_count: int
    items: list[PublicationImportItemResult]


class PublicationIdentifiers(BaseModel):
    doi: str | None = None
    pmid: str | None = None
    pmcid: str | None = None


class PublicationVerificationSummary(BaseModel):
    record_id: UUID
    source_row_number: int
    awardee_name: str | None
    title: str
    journal_name: str | None
    publication_year: int | None
    identifiers: PublicationIdentifiers
    verification_state: str
    conflict_count: int
    evidence_source_count: int
    minimum_match_score: float | None
    layer_statuses: dict[str, str] = Field(default_factory=dict)
    fulltext_preverification_status: str | None = None
    updated_at: datetime


class PublicationVerificationPage(BaseModel):
    items: list[PublicationVerificationSummary]
    total: int
    page: int
    page_size: int
    state_counts: dict[str, int]
    fulltext_preverification_counts: dict[str, int] = Field(default_factory=dict)


class FieldVerificationView(BaseModel):
    field_name: str
    source_value: object | None
    candidate_value: object | None
    candidate_source_code: str | None
    candidate_external_id: str | None
    match_score: float | None
    verification_status: str
    difference_type: str | None
    decision_reason: str | None
    source_url: str | None


class VerificationDecisionView(BaseModel):
    decision: str
    decision_reason: str
    decision_method: str
    decided_by: UUID
    decided_at: datetime


class VerificationCheckView(BaseModel):
    check_code: str
    check_label: str
    check_status: str
    severity: str
    source_value: object | None
    authoritative_value: object | None
    evidence_sources: list[str]
    details: dict[str, object]
    decision_reason: str | None


class VerificationLayerView(BaseModel):
    layer_code: Literal["identity", "attribution", "enrichment"]
    layer_status: str
    is_blocking: bool
    check_count: int
    passed_count: int
    conflict_count: int
    missing_count: int
    rule_version: str
    evaluated_at: datetime | None
    checks: list[VerificationCheckView]


class PublicationIncrementalStatus(BaseModel):
    publication_id: UUID
    metadata_version: int
    identity_state: str
    enrichment_state: str
    fulltext_state: str
    open_supplement_count: int
    latest_supplement_at: datetime | None


class FulltextPreverificationCheckView(BaseModel):
    code: str
    label: str
    status: Literal["passed", "review_required", "conflict", "missing"]
    source_value: object | None = None
    fulltext_value: object | None = None
    reason: str


class FulltextPreverificationView(BaseModel):
    preverification_id: UUID
    content_checksum: str
    source_path: str
    file_name: str
    size_bytes: int
    page_count: int | None
    text_length: int | None
    extraction_method: str | None
    match_confidence: str
    match_score: float
    preverification_status: str
    proposed_metadata: dict[str, object]
    proposed_identifiers: PublicationIdentifiers
    checks: list[FulltextPreverificationCheckView]
    shared_source_rows: list[int]
    rule_version: str
    evaluated_at: datetime


class PublicationVerificationDetail(BaseModel):
    record_id: UUID
    batch_id: UUID
    source_sheet: str | None
    source_row_number: int
    awardee_name: str | None
    awardee_person_id: UUID | None
    verification_state: str
    matched_publication_id: UUID | None
    raw_payload: dict[str, object]
    normalized_payload: dict[str, object]
    fields: list[FieldVerificationView]
    layers: list[VerificationLayerView] = Field(default_factory=list)
    current_decision: VerificationDecisionView | None
    audit_events: list[dict[str, object]]
    incremental_status: PublicationIncrementalStatus | None = None
    fulltext_preverification: FulltextPreverificationView | None = None
    updated_at: datetime


class PublicationVerificationDecisionCommand(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)
    field_choices: dict[str, Literal["source", "candidate"]] = Field(default_factory=dict)
    field_overrides: dict[str, str | int | None] = Field(default_factory=dict)
    awardee_author_order: int | None = Field(default=None, ge=1)
    corresponding_author_orders: list[int] = Field(default_factory=list)
    co_first_author_orders: list[int] = Field(default_factory=list)
    accepted_check_codes: list[str] = Field(default_factory=list)

    @field_validator("field_overrides")
    @classmethod
    def validate_field_overrides(
        cls, value: dict[str, str | int | None]
    ) -> dict[str, str | int | None]:
        allowed = {"title", "doi", "pmid", "pmcid", "journal_name", "publication_year"}
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise ValueError(f"unsupported field overrides: {', '.join(unknown)}")
        publication_year = value.get("publication_year")
        if publication_year not in (None, ""):
            try:
                year = int(publication_year)
            except (TypeError, ValueError) as exc:
                raise ValueError("publication_year override must be an integer") from exc
            if year < 1500 or year > 2200:
                raise ValueError("publication_year override must be between 1500 and 2200")
            value["publication_year"] = year
        return value


class PublicationVerificationDecisionResult(BaseModel):
    record_id: UUID
    publication_id: UUID | None
    verification_state: str
    decision: str
    outbox_events_created: int


class FundingSupplementInput(BaseModel):
    funder_name: str = Field(min_length=1, max_length=500)
    grant_id: str | None = Field(default=None, max_length=200)
    country: str | None = Field(default=None, max_length=100)
    metadata: dict[str, object] = Field(default_factory=dict)


class FulltextSupplementInput(BaseModel):
    file_name: str = Field(min_length=1, max_length=500)
    storage_uri: str = Field(min_length=1, max_length=2000)
    content_checksum: str = Field(pattern=r"^[A-Fa-f0-9]{64}$")
    mime_type: str = Field(default="application/pdf", min_length=1, max_length=200)
    resource_role: Literal["article", "correction", "supplementary"] = "article"
    size_bytes: int | None = Field(default=None, ge=0)
    license_tags: list[str] = Field(default_factory=list)
    extraction_state: Literal["registered", "extracting", "extracted", "failed"] = "registered"
    extracted_metadata: dict[str, object] = Field(default_factory=dict)


class PublicationSupplementCreate(BaseModel):
    source_kind: Literal["metadata", "fulltext", "funding", "lifecycle", "identifier"]
    source_label: str = Field(min_length=1, max_length=500)
    source_uri: str | None = Field(default=None, max_length=2000)
    content_checksum: str | None = Field(default=None, pattern=r"^[A-Fa-f0-9]{64}$")
    metadata: dict[str, object] = Field(default_factory=dict)
    identifiers: PublicationIdentifiers = Field(default_factory=PublicationIdentifiers)
    funding: list[FundingSupplementInput] = Field(default_factory=list)
    fulltext: FulltextSupplementInput | None = None
    note: str | None = Field(default=None, max_length=1000)


class PublicationChangeCandidateView(BaseModel):
    application_state: str = "pending"
    applied_at: datetime | None = None
    proposal_id: UUID
    field_path: str
    current_value: object | None
    proposed_value: object | None
    change_type: Literal["add", "replace", "confirm", "relation_add"]
    risk_level: Literal["safe", "review", "critical"]
    status: Literal["pending", "auto_applied", "accepted", "rejected"]
    decision_reason: str | None


class PublicationSupplementView(BaseModel):
    submission_id: UUID
    publication_id: UUID
    source_kind: str
    source_label: str
    source_uri: str | None
    content_checksum: str | None
    status: str
    impact: str
    base_version: int
    applied_version: int | None
    decision_reason: str | None
    created_at: datetime
    updated_at: datetime
    candidates: list[PublicationChangeCandidateView] = Field(default_factory=list)


class PublicationFulltextUploadResult(BaseModel):
    supplement: PublicationSupplementView
    file_name: str
    storage_uri: str
    content_checksum: str
    mime_type: str
    size_bytes: int
    object_created: bool


class PublicationFulltextResourceView(BaseModel):
    fulltext_resource_id: UUID
    publication_id: UUID
    submission_id: UUID
    file_name: str
    storage_uri: str
    content_checksum: str
    mime_type: str
    resource_role: Literal["article", "correction", "supplementary"]
    size_bytes: int | None
    license_tags: list[str]
    extraction_state: str
    extraction_method: str | None = None
    extraction_version: str | None = None
    extracted_text_uri: str | None = None
    page_count: int | None = None
    text_length: int | None = None
    ocr_page_count: int | None = None
    extracted_at: datetime | None = None
    extraction_error: str | None = None
    extracted_metadata: dict[str, object] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class PublicationSupplementDecisionCommand(BaseModel):
    decision: Literal["accept", "reject"]
    reason: str = Field(min_length=3, max_length=1000)
    proposal_ids: list[UUID] = Field(default_factory=list)
