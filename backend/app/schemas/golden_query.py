from datetime import datetime
from uuid import UUID

from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

# 답에 반드시 있어야 할 사실 조각. 숫자, 날짜, 이름처럼 답에 그대로 나와야 하는 짧은 문구를 쓴다.
ExpectedFact = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
MAX_EXPECTED_FACTS = 20


class GoldenQueryCreate(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)
    expected_document_ids: list[UUID] = Field(..., min_length=1, max_length=50)
    expected_facts: list[ExpectedFact] | None = Field(None, max_length=MAX_EXPECTED_FACTS)


class GoldenQueryUpdate(BaseModel):
    """보낸 항목만 바꾼다(v3 마일스톤 7)."""
    query: str | None = Field(None, min_length=1, max_length=1000)
    expected_document_ids: list[UUID] | None = Field(None, min_length=1, max_length=50)
    # 빈 목록을 보내면 기대 사실을 지운다
    expected_facts: list[ExpectedFact] | None = Field(None, max_length=MAX_EXPECTED_FACTS)


class GoldenQueryResponse(BaseModel):
    id: UUID
    collection_id: UUID
    query: str
    expected_document_ids: list[UUID]
    expected_facts: list[str] | None = None
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
    # 답변까지 평가한 실행에서, 기대 사실이 있는 질의에만 채운다(2026-11-16)
    expected_facts: list[str] | None = None
    facts_found: list[str] | None = None
    fact_recall: float | None = None
    # DONE, FAILED. 답 본문은 실행한 사람과 관리자에게만 보인다
    answer_status: str | None = None
    answer: str | None = None
    citation_count: int | None = None


class GoldenEvalRunRequest(BaseModel):
    # 비우면 컬렉션 검색 설정의 근거 수(채팅이 쓰는 값)로 평가한다
    top_k: int | None = Field(None, ge=1, le=20)
    # 켜면 기대 사실이 있는 질의마다 실제 답을 만들어 사실 적중률을 잰다. 질의마다 LLM을 한 번 쓴다
    with_answers: bool = False


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
    with_answers: bool = False
    mean_fact_recall: float | None = None
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
