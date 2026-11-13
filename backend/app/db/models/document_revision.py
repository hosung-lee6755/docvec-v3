from datetime import datetime
from uuid import uuid4

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.db.types import UTCDateTime

from app.db.base import Base

# 청크 분할이 남기는 분석용 최종 텍스트(정제·사전 적용·개인정보 마스킹 반영). 분석 입력 블록이 읽고,
# 마스킹된 텍스트라 버전 이력 목록과 복원 대상에서는 뺀다.
NORMALIZED_REVISION_SOURCE = "NORMALIZED"
# 사람이 고르거나 복원할 수 있는 원문 계열 스냅샷만 버전 이력에 보인다.
INTERNAL_REVISION_SOURCES = (NORMALIZED_REVISION_SOURCE,)


class DocumentTextRevision(Base):
    """Snapshot of a document's parsed_text taken every time the RAG source
    text is (re)established — at parse, at review-stage edit, at RAG-data edit,
    and at restore. Enables audit (who/when/what) and rollback: restoring a
    revision re-runs chunking/embedding with its parsed_text."""

    __tablename__ = "document_text_revisions"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    document_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        index=True,
    )
    # PARSE | CLEAN | NORMALIZED | REVIEW_EDIT | RAG_EDIT | RESTORE
    source: Mapped[str] = mapped_column(String(20))
    parsed_text: Mapped[str] = mapped_column(Text)
    # Null for system-generated snapshots (PARSE).
    created_by: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow)
