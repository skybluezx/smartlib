from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class JournalMetricReleaseView(BaseModel):
    release_id: UUID
    data_asset_version_id: UUID
    metric_system: Literal["jcr", "cas_partition"]
    edition_year: int
    metric_year: int
    release_label: str
    publisher_name: str
    authority_status: Literal["unverified", "verified", "rejected"]
    release_state: Literal["staged", "validated", "published", "rejected", "superseded"]
    expected_record_count: int
    actual_record_count: int
    license_effective: bool
    source_authorization_state: str
    source_file_checksum: str
    created_at: datetime
    verified_at: datetime | None


class PublicationJournalMetricView(BaseModel):
    match_id: UUID
    publication_id: UUID
    release_id: UUID
    metric_system: Literal["jcr", "cas_partition"]
    edition_year: int
    metric_year: int
    journal_id: UUID
    journal_title: str
    issn: str | None
    eissn: str | None
    categories: list[str]
    citation_indexes: list[str]
    impact_factor: float | None
    impact_factor_is_upper_bound: bool
    quartile: Literal["Q1", "Q2", "Q3", "Q4"] | None
    rank_position: int | None
    rank_total: int | None
    record_granularity: Literal["journal", "journal_category"]
    match_basis: Literal["issn", "eissn", "title", "manual"]
    match_state: Literal["candidate", "matched", "review_required", "rejected"]
    confidence: float
    year_policy: Literal["publication_year", "latest_available", "manual"]
    decision_reason: str | None
