"""화면 알림(전체 점검 2-7, 2026-11-16).

문서 처리 실패, 검토 대기, 파일 서버 동기화 실패를 받는 사람별로 한 줄씩 남긴다. 화면 위쪽의 종
모양 단추가 이 표를 읽는다.
"""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import UTCDateTime

KIND_DOCUMENT_FAILED = "document_failed"
KIND_REVIEW_WAITING = "review_waiting"
KIND_SYNC_FAILED = "sync_failed"
KIND_INQUIRY_CREATED = "inquiry_created"
KIND_INQUIRY_REPLIED = "inquiry_replied"
KIND_INQUIRY_FOLLOWUP = "inquiry_followup"


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user_created", "user_id", "created_at"),)

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 눌렀을 때 갈 화면 경로(예: /documents/<id>)
    link: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # 같은 대상의 읽지 않은 알림이 이미 있으면 새로 만들지 않는다(재시도마다 쌓이지 않게)
    resource_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow)
    read_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
