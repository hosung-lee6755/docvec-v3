from datetime import datetime
from uuid import uuid4

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import UTCDateTime


class UserGroup(Base):
    """데이터 접근 권한을 묶어서 주기 위한 사용자 그룹(v3 권한 모델).

    시스템 역할(User.role: viewer/editor/admin)과는 별개다 — 그룹은 문서 ACL의
    주체(principal)로만 쓰인다(app/services/access_policy.py).
    """

    __tablename__ = "user_groups"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class UserGroupMember(Base):
    __tablename__ = "user_group_members"

    group_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_groups.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    added_by: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow)
