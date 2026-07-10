from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ProjectApiKey(Base):
    __tablename__ = "project_api_keys"
    __table_args__ = (
        UniqueConstraint("project_id", "provider", name="uq_project_api_keys_project_provider"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[str] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"))
    provider: Mapped[str] = mapped_column(
        SQLEnum("openai", "anthropic", name="api_key_provider")
    )
    encrypted_key: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
