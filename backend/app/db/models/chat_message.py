from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, ForeignKey, String, Text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.db.types import UTCDateTime

from app.db.base import Base


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    conversation_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chat_conversations.id")
    )
    query: Mapped[str] = mapped_column(Text)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    citations: Mapped[list | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(
        SQLEnum("PENDING", "GENERATING", "DONE", "FAILED", name="chat_message_status"),
        default="PENDING",
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # v3 마일스톤 5: standard(일반) 또는 deep(심층 검색). deep이면 하위 질문별 검색 과정을 agent_steps에 남긴다
    mode: Mapped[str] = mapped_column(String(10), default="standard", server_default="standard", nullable=False)
    agent_steps: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # v3 마일스톤 6: 사전의 검색어 확장(SEARCH_EXPAND)으로 질문에 덧붙인 낱말
    expanded_terms: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # 사용자 평가(2026-11-16): "up" 또는 "down". 평가하지 않았으면 null
    feedback: Mapped[str | None] = mapped_column(String(10), nullable=True, index=True)
    feedback_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    feedback_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow)
