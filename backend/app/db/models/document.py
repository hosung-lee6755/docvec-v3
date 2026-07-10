from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    String,
    Integer,
    Boolean,
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    filename: Mapped[str] = mapped_column(String(512))
    original_filename: Mapped[str] = mapped_column(String(512))
    file_size: Mapped[int] = mapped_column(Integer)
    mime_type: Mapped[str] = mapped_column(String(100))
    file_hash: Mapped[str] = mapped_column(String(128), index=True)
    minio_key: Mapped[str] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(
        SQLEnum(
            "QUEUED",
            "INGESTING",
            "PARSING",
            "STRUCTURING",
            "REVIEW_PENDING",
            "REFINING",
            "NORMALIZING",
            "CHUNKING",
            "EMBEDDING",
            "UPLOADING",
            "INDEXED",
            "FAILED",
            "CANCELLED",
            name="document_status",
        ),
        default="QUEUED",
        index=True,
    )
    collection_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("collections.id"), nullable=True
    )
    created_by: Mapped[str] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    parsed_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    ocr_used: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # List of [end_offset, page_number] pairs marking cumulative character offsets
    # into parsed_text where each source page ends — see _build_page_map in
    # app/pipeline/tasks/process.py. Used to attribute chunks to a page number for
    # RAG citations; may drift after a manual REVIEW_PENDING text edit.
    page_map: Mapped[list | None] = mapped_column(JSON, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Plain string, not SQLEnum: PENDING -> GENERATING -> DONE | FAILED, set by
    # app/pipeline/tasks/summary.py::generate_summary, triggered automatically
    # once a document reaches INDEXED (see process.py::continue_processing).
    summary_status: Mapped[str] = mapped_column(
        String(20), default="PENDING", server_default="PENDING"
    )
    # Structured table data extracted alongside parsed_text, independent of the
    # flattened "[표 N]" text blocks embedded in parsed_text/chunks — see
    # RawTableCandidate. Shape: [{"page_number": int, "rows": list[list[str]]}].
    # Exposed via GET /documents/{id}/tables and the "표 데이터" tab.
    tables: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Embedded figure/image records extracted at parse time — see
    # _recognize_document_images in app/pipeline/tasks/process.py.
    # Shape: [{"page_number": int, "storage_key": str, "text": str}], where
    # storage_key points into the artifacts MinIO bucket and text holds the
    # OCR/VLM-recognized content (empty string when recognition found nothing).
    images: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # User-managed labels (list[str]) copied into each chunk's Qdrant payload at
    # index time so retrieval can filter by tag — see continue_processing.
    tags: Mapped[list | None] = mapped_column(JSON, nullable=True)
