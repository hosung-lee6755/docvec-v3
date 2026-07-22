from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, Integer, String, DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID

from app.core.config import settings
from app.db.base import Base


class Collection(Base):
    __tablename__ = "collections"
    __table_args__ = (
        # Collections are private per account; qdrant_collection_name is a legacy
        # field not actually used for storage routing (all collections currently
        # share one physical Qdrant collection), so uniqueness must be scoped to
        # the owner, not global, or one account's name choice blocks every other
        # account from ever using it.
        UniqueConstraint(
            "created_by", "qdrant_collection_name", name="uq_collection_owner_qdrant_name"
        ),
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    name: Mapped[str] = mapped_column(String(255), index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    qdrant_collection_name: Mapped[str] = mapped_column(String(255))
    embedding_model: Mapped[str] = mapped_column(
        String(64), default=settings.default_embedding_model
    )
    chunk_max_tokens: Mapped[int] = mapped_column(
        Integer, default=settings.default_chunk_max_tokens
    )
    chunk_min_tokens: Mapped[int] = mapped_column(
        Integer, default=settings.default_chunk_min_tokens
    )
    chunk_overlap_tokens: Mapped[int] = mapped_column(
        Integer, default=settings.default_chunk_overlap_tokens
    )
    # "size" (character-count cut at paragraph boundaries) or "semantic"
    # (sentence-embedding similarity boundaries) — see process.py chunkers.
    chunk_strategy: Mapped[str] = mapped_column(
        String(20), default="size", server_default="size"
    )
    # Tracks the background job kicked off when embedding_model changes on a
    # collection that already has documents — see tasks/reembed.py. None when no
    # re-embed has ever run; PENDING/RUNNING/COMPLETED/FAILED while one has.
    reembed_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Human-readable "3/10" style progress string, updated as reembed_collection
    # works through the collection's documents.
    reembed_progress: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_by: Mapped[str] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    # Optional parent project. When set, every project member gets automatic viewer+
    # access to this collection (see api/v1/permissions.py) unless restrict_to_members
    # is on, in which case only explicit CollectionMember rows (a subset of the
    # project's members) get access — the mechanism for excluding some project
    # members from a specific collection.
    project_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True
    )
    restrict_to_members: Mapped[bool] = mapped_column(Boolean, default=False)
    # The preprocessing workflow run automatically against every document
    # uploaded into this collection. Null means "use the system default
    # workflow" (seeded, always ACTIVE — see workflow_service). Null version
    # means "always the latest published version at run time".
    default_workflow_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_definitions.id", ondelete="SET NULL"), nullable=True
    )
    default_workflow_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # The ANALYSIS workflow run automatically against a document right after its
    # PREPROCESS run completes (RAG 저장 성공 직후) — see _maybe_trigger_analysis
    # in tasks/workflow.py. Null means "no automatic analysis" (documents can
    # still be analyzed manually via a workflow's 실행 button).
    default_analysis_workflow_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_definitions.id", ondelete="SET NULL"), nullable=True
    )
    default_analysis_workflow_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
