from datetime import datetime

from sqlalchemy import Enum as SQLEnum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
from app.db.types import UTCDateTime

from app.db.base import Base


class DictionaryRevision(Base):
    """A global, monotonically increasing version counter over all
    dictionary_entries writes — 전처리 워크플로우 통합 설계서 §4.8 / §5. Every
    create/update/delete/import through dictionary_service adds one row here
    in the same transaction and bumps the version. A WorkflowRun pins the
    version current at its start time so dictionary blocks stay reproducible
    even as the dictionary keeps changing underneath later runs."""

    __tablename__ = "dictionary_revisions"

    version: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    changed_entry_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dictionary_entries.id", ondelete="SET NULL"), nullable=True
    )
    change_type: Mapped[str] = mapped_column(
        SQLEnum("CREATE", "UPDATE", "DELETE", "IMPORT", name="dictionary_change_type"),
    )
    # Populated only for bulk changes where a full point-in-time snapshot is
    # cheaper to keep than reconstructing "as of version N" from row history.
    snapshot_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_by: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow)
