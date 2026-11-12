from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class GoldenQueryCreate(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)
    expected_document_ids: list[UUID] = Field(..., min_length=1, max_length=50)


class GoldenQueryUpdate(BaseModel):
    """보낸 항목만 바꾼다(v3 마일스톤 7)."""
    query: str | None = Field(None, min_length=1, max_length=1000)
    expected_document_ids: list[UUID] | None = Field(None, min_length=1, max_length=50)


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
    # 요청자가 볼 수 없는 기대 문서가 있으면 질의별 점수를 가린다(masked=True, 점수는 null)
    precision: float | None = None
    recall: float | None = None
    # v3 마일스톤 7. 이전 실행에는 없다
    hit: bool | None = None
    reciprocal_rank: float | None = None
    first_hit_rank: int | None = None
    masked: bool = False


class GoldenEvalRunRequest(BaseModel):
    # 비우면 컬렉션 검색 설정의 근거 수(채팅이 쓰는 값)로 평가한다
    top_k: int | None = Field(None, ge=1, le=20)


class GoldenEvalRunResponse(BaseModel):
    id: UUID
    collection_id: UUID
    top_k: int
    # QUEUED, RUNNING, DONE, FAILED
    status: str = "DONE"
    # manual, search_settings, dictionary, new_version, lifecycle, document_deleted
    trigger: str = "manual"
    mean_precision: float | None = None
    mean_recall: float | None = None
    mean_hit_rate: float | None = None
    mean_mrr: float | None = None
    is_baseline: bool = False
    is_regression: bool | None = None
    regression: dict | None = None
    search_settings: dict | None = None
    error_message: str | None = None
    results: list[GoldenEvalQueryResult] | None = None
    created_at: datetime
    completed_at: datetime | None = None

    class Config:
        from_attributes = True


class GoldenEvalRunListResponse(BaseModel):
    items: list[GoldenEvalRunResponse]
