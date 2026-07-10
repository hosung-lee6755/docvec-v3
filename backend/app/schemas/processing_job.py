from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ProcessingJobItem(BaseModel):
    id: UUID
    job_type: str
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    result_summary: str | None
    error_message: str | None

    class Config:
        from_attributes = True


class ProcessingJobListResponse(BaseModel):
    items: list[ProcessingJobItem]
