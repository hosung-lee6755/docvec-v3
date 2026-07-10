from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class GoldenQueryCreate(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)
    expected_document_ids: list[UUID] = Field(..., min_length=1)


class GoldenQueryResponse(BaseModel):
    id: UUID
    collection_id: UUID
    query: str
    expected_document_ids: list[UUID]
    created_at: datetime

    class Config:
        from_attributes = True


class GoldenQueryListResponse(BaseModel):
    items: list[GoldenQueryResponse]


class GoldenEvalQueryResult(BaseModel):
    golden_query_id: UUID
    query: str
    expected_document_ids: list[UUID]
    retrieved_document_ids: list[UUID]
    precision: float
    recall: float


class GoldenEvalRunRequest(BaseModel):
    top_k: int = Field(5, ge=1, le=50)


class GoldenEvalRunResponse(BaseModel):
    id: UUID
    collection_id: UUID
    top_k: int
    mean_precision: float
    mean_recall: float
    results: list[GoldenEvalQueryResult]
    created_at: datetime

    class Config:
        from_attributes = True


class GoldenEvalRunListResponse(BaseModel):
    items: list[GoldenEvalRunResponse]
