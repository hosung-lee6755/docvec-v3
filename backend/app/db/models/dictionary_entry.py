from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.dictionary_entry_variant import DictionaryEntryVariant


class DictionaryEntry(Base):
    """A stopword / synonym / custom-word ("user dictionary") entry used to
    build the kiwipiepy-based Korean tokenizer for BM25 keyword search — see
    app/services/dictionary_service.py. Field layout follows
    문서_처리_사전_스키마.md: `term` holds the stopword's excluded word, the
    synonym group's canonical term, or the user dictionary's standard term;
    type-specific columns are nullable and only meaningful for their own
    entry_type (see §1-3 of the schema doc for which)."""

    __tablename__ = "dictionary_entries"
    __table_args__ = (
        UniqueConstraint("entry_type", "term", name="uq_dictionary_entry_type_term"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    entry_type: Mapped[str] = mapped_column(String(20), index=True)
    term: Mapped[str] = mapped_column(String(255))

    # Stopword only — EXACT | CONTAINS | PREFIX | SUFFIX | REGEX
    match_type: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Synonym only
    direction: Mapped[str | None] = mapped_column(String(20), nullable=True)  # ONE_WAY | BIDIRECTIONAL
    processing_mode: Mapped[str | None] = mapped_column(String(20), nullable=True)  # NORMALIZE | REPLACE | SEARCH_EXPAND | TAGGING

    # Custom word (user dictionary) only
    term_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    processing_rule: Mapped[str | None] = mapped_column(String(20), nullable=True)  # KEEP | NORMALIZE | REPLACE | TAG | EXTRACT | MASK | IGNORE
    pronunciation: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Common to all three types
    case_sensitive: Mapped[bool] = mapped_column(Boolean, default=False)
    language: Mapped[str] = mapped_column(String(10), default="ko")
    scope: Mapped[list] = mapped_column(JSON, default=list)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    created_by: Mapped[str] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    variants: Mapped[list[DictionaryEntryVariant]] = relationship(
        back_populates="entry",
        cascade="all, delete-orphan",
        order_by=DictionaryEntryVariant.sort_order,
    )
