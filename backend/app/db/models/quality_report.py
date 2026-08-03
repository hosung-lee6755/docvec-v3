from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, Enum as SQLEnum, Float, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
from app.db.types import UTCDateTime

from app.db.base import Base


class QualityReport(Base):
    """One quality_check block execution's result — 전처리 워크플로우 통합
    설계서 §4.7 / 문서데이터 전처리 방안.md §12. `run_id` is unique: a report
    belongs to exactly one run, and a run produces at most one report (the
    quality_check block runs once per run). `status` doubles as the review
    gate's decision — REVIEW_REQUIRED is what flips the run to WAITING_REVIEW."""

    __tablename__ = "quality_reports"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    run_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_runs.id", ondelete="CASCADE"), unique=True, index=True
    )
    document_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    overall_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    # {textExtraction, ocr, structure, normalization, chunking} — §12.3.
    scores: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Raw file/text/structure/dictionary/chunking level metrics — §12.2.
    metrics: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    warnings: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # warnings와 같은 순서/길이 — 각 경고가 어느 카테고리(textExtraction/ocr/
    # structure/chunking)에서 나왔는지. 프런트가 경고를 클릭하면 해당 탭으로
    # 바로 이동시키는 데 쓴다.
    warning_categories: Mapped[list | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(
        SQLEnum(
            "SUCCESS", "SUCCESS_WITH_WARNING", "REVIEW_REQUIRED", "PARTIAL_FAILURE", "FAILURE",
            name="quality_report_status",
        ),
    )
    reviewed_by: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow)
