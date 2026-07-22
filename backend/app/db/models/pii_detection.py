from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Enum as SQLEnum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base


class PiiDetection(Base):
    """One sensitive-data detection produced by the pii_detect block —
    전처리 워크플로우 통합 설계서 §4.5 / 문서데이터 전처리 방안.md §10.
    `original_encrypted` holds the unmasked value under application-level
    encryption (see app/core/crypto — wired in Phase 5); only `masked_value`
    is ever shown without an explicit unmask permission check."""

    __tablename__ = "pii_detections"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    run_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_runs.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    entity_type: Mapped[str] = mapped_column(String(50))
    action: Mapped[str] = mapped_column(
        SQLEnum("MARK", "MASK", "TOKENIZE", "REMOVE", "EXCLUDE_EMBEDDING", name="pii_action"),
    )
    original_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    masked_value: Mapped[str | None] = mapped_column(String(255), nullable=True)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    node_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_nodes.id", ondelete="SET NULL"), nullable=True
    )
    start_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    approved_by: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # 오탐(false positive) 표시 — 민감정보 탭의 [해제] 액션. DictionaryApplication.reverted와
    # 동일하게 즉시 데이터 변경 없이 다음 부분 재처리 대상으로만 표시한다.
    rejected: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
