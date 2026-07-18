from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Enum as SQLEnum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base


class CleaningRule(Base):
    """A user-managed text-cleaning rule — 문서데이터 전처리 방안.md §8.3. BUILTIN
    rows represent the always-available regex rules already hard-coded in
    text_clean (whitespace collapse, unicode normalize, ...); they exist here
    so the 정제 규칙 screen can show/toggle them alongside user-authored ones,
    and so `created_by` stays nullable (a BUILTIN row has no human author)."""

    __tablename__ = "cleaning_rules"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    rule_name: Mapped[str] = mapped_column(String(255))
    rule_type: Mapped[str] = mapped_column(
        SQLEnum("REGEX_REPLACE", "EXACT_REMOVE", "LINE_FILTER", "BUILTIN", name="cleaning_rule_type"),
    )
    pattern: Mapped[str | None] = mapped_column(Text, nullable=True)
    replacement: Mapped[str | None] = mapped_column(Text, nullable=True)
    scope: Mapped[str] = mapped_column(
        SQLEnum("DOCUMENT", "PARAGRAPH", "LINE", name="cleaning_rule_scope"),
        default="PARAGRAPH",
        server_default="PARAGRAPH",
    )
    priority: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class CleaningChange(Base):
    """One rule-application entry produced by the text_clean block —
    문서데이터 전처리 방안.md §8.4. `before_sample`/`after_sample` hold a
    representative excerpt rather than the full change list; `change_count`
    is the true total for rules that fire many times per document (e.g. a
    repeated-header removal across 42 pages)."""

    __tablename__ = "cleaning_changes"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    run_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_runs.id", ondelete="CASCADE"), index=True
    )
    step_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_run_steps.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    rule_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cleaning_rules.id", ondelete="SET NULL"), nullable=True
    )
    # Identifies a built-in rule not (yet) backed by a CleaningRule row.
    rule_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    node_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_nodes.id", ondelete="SET NULL"), nullable=True
    )
    before_sample: Mapped[str | None] = mapped_column(Text, nullable=True)
    after_sample: Mapped[str | None] = mapped_column(Text, nullable=True)
    change_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
