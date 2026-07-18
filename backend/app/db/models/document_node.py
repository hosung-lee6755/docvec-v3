from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, Enum as SQLEnum, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base


class DocumentNode(Base):
    """One node in a document's structure tree, produced by the structure_analyze
    block — 전처리 워크플로우 통합 설계서 §4.2 / 문서데이터 전처리 방안.md §7.
    `span_start`/`span_end` are character offsets into the owning document's
    `parsed_text`, the mechanism the 원문 대조 tab uses to trace a node back to
    its exact source location."""

    __tablename__ = "document_nodes"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    document_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    # Which run's structure_analyze produced this tree — a reprocess replaces
    # the whole tree rather than mutating the previous run's nodes.
    run_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_runs.id", ondelete="CASCADE"), index=True
    )
    node_type: Mapped[str] = mapped_column(
        SQLEnum(
            "DOCUMENT", "COVER", "TOC", "SECTION", "HEADING", "PARAGRAPH", "SENTENCE",
            "LIST", "LIST_ITEM", "TABLE", "TABLE_ROW", "TABLE_CELL", "IMAGE", "CAPTION",
            "FOOTNOTE", "HEADER", "FOOTER", "PAGE_NUMBER", "FORM_FIELD",
            name="document_node_type",
        ),
    )
    level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    parent_node_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_nodes.id", ondelete="CASCADE"), nullable=True
    )
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    span_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    span_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    style: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Set once a user edits this node's level/type/boundary via the 구조 tab —
    # 설계서 §19.2 사용자 수정 기능, distinct from the original analyzer output.
    user_corrected: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
