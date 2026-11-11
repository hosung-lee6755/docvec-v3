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
    # 보내지 않으면 컬렉션 검색 설정(v3 마일스톤 6)을 따른다. 컬렉션을 고르지 않았으면 기본값이다
    mode: SearchMode | None = None
    diversify: bool | None = None

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
    # v3 마일스톤 6: 질문과 겹친 낱말, 그 쪽의 OCR 신뢰도와 기준 미달 여부
    evidence: dict | None = None


class AppliedSearchSettings(BaseModel):
    """이번 검색에 실제로 쓴 방식. 재순위는 채팅에만 적용하므로 rerank는 컬렉션 설정을 알려 주기만 한다."""
    mode: SearchMode
    diversify: bool
    vector_weight: float
    rerank_in_chat: bool
    from_collection: bool


class SearchResponse(BaseModel):
    items: list[SearchResultItem]
    expanded_query: str
    added_terms: list[str] = Field(default_factory=list)
    applied: AppliedSearchSettings | None = None


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
