from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class InputRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_record_key: str = Field(min_length=1, max_length=1000)
    record_kind: str = Field(min_length=1, max_length=100)
    source_locator: dict[str, object] = Field(default_factory=dict)
    raw_payload: dict[str, object]


class IngestionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_system_id: UUID
    dataset_version: str = Field(min_length=1, max_length=500)
    source_kind: Literal["file", "api", "manual", "connector", "stream"]
    pipeline_key: str = Field(min_length=1, max_length=100)
    source_uri: str | None = Field(default=None, min_length=1, max_length=2000)
    source_checksum: str | None = Field(default=None, pattern=r"^[A-Fa-f0-9]{64}$")
    source_locator: dict[str, object] = Field(default_factory=dict)
    records: list[InputRecord] = Field(min_length=1, max_length=5000)

    @model_validator(mode="after")
    def unique_source_keys(self) -> IngestionCreate:
        if len({r.source_record_key for r in self.records}) != len(self.records):
            raise ValueError("source_record_key must be unique within a batch")
        if not self.dataset_version.strip() or not self.pipeline_key.strip():
            raise ValueError("dataset_version and pipeline_key must not be blank")
        if any(not r.source_record_key.strip() or not r.record_kind.strip() for r in self.records):
            raise ValueError("source_record_key and record_kind must not be blank")
        return self


class IngestionResult(BaseModel):
    batch_id: UUID
    record_ids: list[UUID]
    reused: bool = False
