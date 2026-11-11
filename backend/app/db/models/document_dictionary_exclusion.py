from datetime import datetime

from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import UTCDateTime


class DocumentDictionaryExclusion(Base):
    """문서 하나에서 끈 사전 항목(v3 마일스톤 6). 불용어, 동의어, 사용자 사전 블록이 다음 처리부터
    이 문서에서는 그 항목을 건너뛴다. 사전 항목 자체(전역 enabled)는 건드리지 않는다."""

    __tablename__ = "document_dictionary_exclusions"

    document_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True
    )
    entry_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dictionary_entries.id", ondelete="CASCADE"), primary_key=True
    )
    created_by: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow)
