from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Scope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_year: int | None = Field(default=None, ge=1500, le=2200)
    end_year: int | None = Field(default=None, ge=1500, le=2200)
    organization_id: UUID | None = None
    custom_scope_id: UUID | None = None

    @model_validator(mode="after")
    def ordered(self):
        if self.start_year and self.end_year and self.start_year > self.end_year:
            raise ValueError("开始年份不能晚于结束年份")
        return self


Category = Literal[
    "recruitment", "cultivation", "teams", "transfer", "research", "disciplines", "resources", "overview"
]


class MatterCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    category: Category
    title: str = Field(min_length=2, max_length=160)
    question: str = Field(min_length=5, max_length=4000)
    evidence: str = Field(min_length=3, max_length=4000)
    responsible_unit: str = Field(min_length=1, max_length=200)
    next_step: str = Field(min_length=3, max_length=2000)
    review_on: date
    status: Literal["proposed", "investigating", "tracking", "closed"] = "proposed"
    object_ids: list[UUID] = Field(default_factory=list, max_length=100)
    supersedes_id: UUID | None = None
    scope: Scope = Field(default_factory=Scope)


class ReportCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=2, max_length=160)
    scope: Scope = Field(default_factory=Scope)
