from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, DateTime, Enum as SQLEnum, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    version_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_versions.id"), index=True
    )
    document_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id"), nullable=True
    )
    collection_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("collections.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        SQLEnum("QUEUED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED", name="workflow_run_status"),
        default="QUEUED",
        index=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class WorkflowRunStep(Base):
    __tablename__ = "workflow_run_steps"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    run_id: Mapped[str] = mapped_column(UUID(as_uuid=True), ForeignKey("workflow_runs.id"), index=True)
    block_instance_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_block_instances.id")
    )
    status: Mapped[str] = mapped_column(
        SQLEnum("PENDING", "RUNNING", "COMPLETED", "FAILED", name="workflow_run_step_status"),
        default="PENDING",
        index=True,
    )
    # Number of incoming edges that have fired so far. Only meaningful for 병합
    # blocks with >1 incoming edge — the executor enqueues this step once this
    # count reaches the block's total incoming-edge count (see tasks/workflow.py).
    completed_incoming_edges: Mapped[int] = mapped_column(Integer, default=0)
    input: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
