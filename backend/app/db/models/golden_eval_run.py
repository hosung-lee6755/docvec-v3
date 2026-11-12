from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
from app.db.types import UTCDateTime

from app.db.base import Base


class GoldenEvalRun(Base):
    """One execution of the golden-query evaluation for a collection — runs
    every GoldenQuery through the same retrieval path as chat/search and
    records precision/recall per query plus the aggregate mean."""

    __tablename__ = "golden_eval_runs"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    collection_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("collections.id"), index=True
    )
    created_by: Mapped[str] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    top_k: Mapped[int] = mapped_column(Integer)
    # 비어 있으면 아직 끝나지 않은 실행이다(v3 마일스톤 7부터 워커에서 비동기로 돈다)
    mean_precision: Mapped[float | None] = mapped_column(Float, nullable=True)
    mean_recall: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Per-query breakdown: [{golden_query_id, query, expected_document_ids,
    # retrieved_document_ids, precision, recall}, ...]
    results: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # QUEUED → RUNNING → DONE | FAILED
    status: Mapped[str] = mapped_column(String(20), default="QUEUED", server_default="DONE")
    # manual, search_settings, dictionary, new_version, lifecycle, document_deleted
    trigger: Mapped[str] = mapped_column(String(30), default="manual", server_default="manual")
    mean_hit_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    mean_mrr: Mapped[float | None] = mapped_column(Float, nullable=True)
    # 컬렉션마다 하나. 회귀는 이 실행과 비교한다
    is_baseline: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_regression: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # {"baseline_run_id", "metrics": {name: {baseline, current, delta}}, "lost_queries": [...]}
    regression: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # 평가에 쓴 컬렉션 검색 설정 사본(회귀 원인 추적용)
    search_settings: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow)
