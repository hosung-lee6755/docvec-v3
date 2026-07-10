import json
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

SearchMode = Literal["vector", "hybrid"]

_MAX_FILTERS_JSON_BYTES = 5000


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)
    collection_id: UUID | None = None
    project_id: UUID | None = None
    limit: int = Field(10, gt=0, le=100)
    filters: dict | None = None
    mode: SearchMode = "vector"

    @field_validator("filters")
    @classmethod
    def _bound_filters_size(cls, v: dict | None) -> dict | None:
        if v is not None and len(json.dumps(v)) > _MAX_FILTERS_JSON_BYTES:
            raise ValueError(f"filters exceeds {_MAX_FILTERS_JSON_BYTES} bytes")
        return v


class SearchResultItem(BaseModel):
    chunk_id: str
    score: float
    document_id: UUID
    content: str
    metadata: dict
    bm25_score: float | None = None
    final_score: float | None = None


class SearchHistoryItem(BaseModel):
    id: UUID
    query: str
    collection_id: UUID | None
    result_count: int
    search_mode: str
    created_at: datetime

    class Config:
        from_attributes = True


class SearchHistoryResponse(BaseModel):
    items: list[SearchHistoryItem]
