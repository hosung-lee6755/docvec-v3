from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class DictionaryEntryVariant(Base):
    """A single alias for a DictionaryEntry: a synonym string (entry_type
    "synonym") or an alias/typo/spacing variant of a standard term (entry_type
    "custom_word"). Matches 문서_처리_사전_스키마.md §5's dictionary_term_variant
    table — kept as its own table rather than a delimited string column so
    variants can be queried/edited individually."""

    __tablename__ = "dictionary_entry_variants"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    entry_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dictionary_entries.id", ondelete="CASCADE"), index=True
    )
    variant_term: Mapped[str] = mapped_column(String(255))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    entry: Mapped["DictionaryEntry"] = relationship(back_populates="variants")
