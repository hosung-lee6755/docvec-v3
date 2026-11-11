"""개인 접근 토큰(v3 마일스톤 4).

직원이 화면에서 발급해 외부 에이전트(MCP 클라이언트)에 넣는다. 에이전트는 그 직원의 권한으로만
움직인다. 토큰 원문은 저장하지 않고 SHA-256만 둔다(무작위 256비트라 느린 해시가 필요 없다).
"""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import UTCDateTime


class PersonalAccessToken(Base):
    __tablename__ = "personal_access_tokens"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    # 목록에서 알아보도록 원문 앞부분만 보관한다(예: dvp_AbC1)
    token_prefix: Mapped[str] = mapped_column(String(16))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    last_used_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    revoked_by: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
