"""관리자 문의(inquiries)와 문의 메시지.

사용자가 지속되는 오류나 질문을 관리자에게 남기고, 관리자와 주고받는다. 문서 처리 실패에서 시작한
문의는 문서 id를 연결하고, 그 시점의 오류 문구(error_snapshot)를 서버가 복사해 둔다.
문의의 첫 본문은 첫 번째 메시지(작성자가 쓴 글)다. 내용 수정은 그 메시지를 고친다.
"""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, ForeignKey, Index, String, Text, false
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import UTCDateTime

CATEGORY_ERROR = "error"
CATEGORY_QUESTION = "question"
CATEGORY_REQUEST = "request"
CATEGORY_OTHER = "other"
INQUIRY_CATEGORIES = (CATEGORY_ERROR, CATEGORY_QUESTION, CATEGORY_REQUEST, CATEGORY_OTHER)

STATUS_OPEN = "open"
STATUS_IN_PROGRESS = "in_progress"
STATUS_RESOLVED = "resolved"
STATUS_CLOSED = "closed"
INQUIRY_STATUSES = (STATUS_OPEN, STATUS_IN_PROGRESS, STATUS_RESOLVED, STATUS_CLOSED)


class Inquiry(Base):
    __tablename__ = "inquiries"
    __table_args__ = (Index("ix_inquiries_status_updated", "status", "updated_at"),)

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    author_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default=STATUS_OPEN)
    # 문서가 지워지면 연결만 끊고 문의는 남긴다
    document_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    # 문의를 낼 때의 문서 오류 문구. 클라이언트가 보낸 값은 쓰지 않고 서버가 문서에서 복사한다
    error_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow)


class InquiryMessage(Base):
    __tablename__ = "inquiry_messages"
    __table_args__ = (Index("ix_inquiry_messages_inquiry_created", "inquiry_id", "created_at"),)

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    inquiry_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inquiries.id", ondelete="CASCADE")
    )
    author_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    body: Mapped[str] = mapped_column(Text)
    # 글을 쓸 때의 역할이 관리자였는지. 나중에 역할이 바뀌어도 대화 기록은 그대로 남는다
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow)
