from datetime import datetime
from uuid import uuid4

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.db.types import UTCDateTime

from app.db.base import Base


class ChatConversation(Base):
    __tablename__ = "chat_conversations"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    project_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True
    )
    collection_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("collections.id"), nullable=True
    )
    model_key: Mapped[str] = mapped_column(Text)
    # v3 마일스톤 4: web=웹 채팅, mcp=외부 에이전트의 ask 도구. MCP 대화는 웹 채팅 목록에 넣지 않는다.
    channel: Mapped[str] = mapped_column(String(10), default="web", server_default="web", nullable=False)
    access_token_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("personal_access_tokens.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
