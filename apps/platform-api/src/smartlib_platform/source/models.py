from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class SourceCreate(BaseModel):
    code: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    name: str = Field(min_length=1, max_length=200)
    owner_department: str = Field(min_length=1, max_length=200)
    source_type: Literal["database", "api", "file", "repository", "licensed_resource", "manual"]
    authorization_state: Literal["pending", "approved", "suspended", "expired", "rejected"] = "pending"
    metadata: dict[str, object] = Field(default_factory=dict)


class SourceView(SourceCreate):
    source_system_id: UUID
    created_at: datetime
    updated_at: datetime
