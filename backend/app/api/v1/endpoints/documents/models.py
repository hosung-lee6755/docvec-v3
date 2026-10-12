from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class BatchDeleteRequest(BaseModel):
    ids: list[UUID] = Field(min_items=1, max_items=100)


class BatchReprocessRequest(BaseModel):
    ids: list[UUID] = Field(min_items=1, max_items=100)


class BatchReprocessItemResult(BaseModel):
    id: UUID
    status: Literal["queued", "skipped", "failed"]
    run_id: UUID | None = None
    detail: str | None = None


class BatchReprocessResponse(BaseModel):
    results: list[BatchReprocessItemResult]


class BulkUploadItemResult(BaseModel):
    filename: str
    status: Literal["queued", "duplicate", "skipped", "failed"]
    document_id: UUID | None = None
    detail: str | None = None


class BulkUploadResponse(BaseModel):
    total_entries: int
    queued: int
    results: list[BulkUploadItemResult]



