from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, Boolean, Enum as SQLEnum, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
from app.db.types import UTCDateTime

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
    # Links a TABLE node back to its Document.tables[*]["id"] entry (문서 파싱
    # 고도화 Phase 3) — the tree/JSON split means a TABLE node's cell data
    # lives in Document.tables, not on the node itself; this is how the UI
    # resolves "which table is this node" without re-matching by content.
    # None for every non-TABLE node, and for TABLE nodes produced before this
    # field existed.
    source_table_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 메타 정보 생성 설계서(2026-07-23) — 이 노드를 만든 Docling
    # elements[*]["id"](structure_blocks.py::_build_blocks_from_elements의
    # layout["element_id"])를 영속화. chunk_strategies.py가 청크의
    # DocumentChunk.element_id를 스탬프할 때 여기서 읽어온다. Legacy 엔진/
    # HWP·HWPX 문서는 항상 None.
    element_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Set once a user edits this node's level/type/boundary via the 구조 tab —
    # 설계서 §19.2 사용자 수정 기능, distinct from the original analyzer output.
    user_corrected: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Audit info alongside user_corrected (문서 파싱 고도화 Phase 4) — no
    # separate correction-history table, just what/why on the node itself.
    # correction_type is a comma-joined list of the fields the correction
    # touched (e.g. "node_type", "level", "node_type,level"), set by
    # correct_document_node(); correction_notes is an optional free-text
    # reason the editor supplied. Both None until the first correction.
    correction_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    correction_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
