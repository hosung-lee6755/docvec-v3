from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, Enum as SQLEnum, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
from app.db.types import UTCDateTime

from app.db.base import Base


class DictionaryApplication(Base):
    """One dictionary-entry application (stopword mark / synonym normalize /
    user-dictionary normalize) recorded by the stopword/synonym/user_dict
    blocks against a specific document — 전처리 워크플로우 통합 설계서 §4.4 /
    문서데이터 전처리 방안.md §9.6. `reverted` implements the 사전 적용 tab's
    "적용 취소" action: marking it true does not change stored text by
    itself, it only flags the application for the next partial reprocess."""

    __tablename__ = "dictionary_applications"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    run_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_runs.id", ondelete="CASCADE"), index=True
    )
    step_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_run_steps.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    dictionary_type: Mapped[str] = mapped_column(
        SQLEnum("STOPWORD", "SYNONYM", "USER_DICT", name="dictionary_application_type"),
    )
    entry_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dictionary_entries.id", ondelete="SET NULL"), nullable=True
    )
    dictionary_version: Mapped[int] = mapped_column(Integer)
    original_text: Mapped[str] = mapped_column(Text)
    normalized_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    node_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_nodes.id", ondelete="SET NULL"), nullable=True
    )
    chunk_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_chunks.id", ondelete="SET NULL"), nullable=True
    )
    start_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reverted: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow)
