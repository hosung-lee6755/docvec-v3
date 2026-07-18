from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base


class DocumentChunk(Base):
    """The RAG chunk as a first-class DB row — 전처리 워크플로우 통합 설계서 §4.6.
    Promotes what previously lived only in the Qdrant point payload into the
    database, so the 청크 tab can list/edit/trace chunks without querying
    Qdrant, and so document deletion, chunk edits, and page/section
    attribution all have one source of truth. `id` is reused verbatim as the
    Qdrant point id at upsert time — see rag_store block (Phase 6)."""

    __tablename__ = "document_chunks"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    document_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_runs.id", ondelete="CASCADE"), index=True
    )
    chunk_order: Mapped[int] = mapped_column(Integer)
    # Cleaned/normalized/masked text — what actually gets embedded.
    chunk_text: Mapped[str] = mapped_column(Text)
    # The corresponding raw parsed_text span, kept for diff/원문 대조.
    original_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section_path: Mapped[list | None] = mapped_column(JSON, nullable=True)
    source_node_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    prev_chunk_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_chunks.id", ondelete="SET NULL"), nullable=True
    )
    next_chunk_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_chunks.id", ondelete="SET NULL"), nullable=True
    )
    span_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    span_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    embedded: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    edited: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    excluded_pii: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    workflow_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dictionary_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
