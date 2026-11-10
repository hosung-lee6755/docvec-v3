from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, String, Text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.db.types import UTCDateTime

from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    username: Mapped[str] = mapped_column(String(255))
    hashed_password: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(
        SQLEnum("viewer", "editor", "admin", name="user_role"),
        default="viewer",
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # v3 권한 모델: 이 사용자가 열람할 수 있는 최고 문서 보안등급(Public < Internal <
    # Confidential). 관리자만 바꾼다. 판정은 app/services/access_policy.py.
    clearance_level: Mapped[str] = mapped_column(
        String(20), default="Internal", server_default="Internal", nullable=False
    )
    # Per-user override for the chat generation system prompt (see
    # app/pipeline/tasks/chat.py's _SYSTEM_PROMPT default). Null = use the default.
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
