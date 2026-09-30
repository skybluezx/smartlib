from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class JobView(BaseModel):
    job_id: UUID
    job_type: str
    state: str
    progress: int
    requested_by: UUID
    trace_id: str | None
    failure_code: str | None
    failure_message: str | None
    created_at: datetime
    updated_at: datetime
