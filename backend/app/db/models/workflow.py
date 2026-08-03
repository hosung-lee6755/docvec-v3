from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, Enum as SQLEnum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
from app.db.types import UTCDateTime

from app.db.base import Base


class WorkflowDefinition(Base):
    __tablename__ = "workflow_definitions"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    # Nullable: a system-owned workflow (e.g. the seeded 표준 전처리 워크플로우,
    # 통합 설계서 §13 Task 3) belongs to no single project.
    project_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), index=True, nullable=True
    )
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        SQLEnum("DRAFT", "ACTIVE", "INACTIVE", name="workflow_status"),
        default="DRAFT",
        index=True,
    )
    # PREPROCESS workflows replace the fixed document pipeline (§7.3 그래프
    # 검증 확장); ANALYSIS workflows are the pre-existing user-defined kind.
    kind: Mapped[str] = mapped_column(
        SQLEnum("PREPROCESS", "ANALYSIS", name="workflow_definition_kind"),
        default="ANALYSIS",
        server_default="ANALYSIS",
    )
    created_by: Mapped[str] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class WorkflowVersion(Base):
    __tablename__ = "workflow_versions"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    workflow_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_definitions.id"), index=True
    )
    version_number: Mapped[int] = mapped_column(Integer)
    # Set only once this version is published. A non-null published_at means the
    # version is immutable — edits must go through a new WorkflowVersion instead
    # of mutating this row (see 활성 버전은 직접 수정하지 않고 새 버전으로 저장한다).
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_by: Mapped[str] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow)


class WorkflowBlockInstance(Base):
    __tablename__ = "workflow_block_instances"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    version_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_versions.id"), index=True
    )
    # Must be a key present in app.pipeline.blocks.registry.BLOCK_REGISTRY.
    block_type: Mapped[str] = mapped_column(String(50))
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Canvas coordinates, e.g. {"x": 120, "y": 40} — display only, not used by the executor.
    position: Mapped[dict] = mapped_column(JSON, default=dict)
    # Block-type-specific settings validated against that block's input_schema.
    config: Mapped[dict] = mapped_column(JSON, default=dict)


class WorkflowEdge(Base):
    __tablename__ = "workflow_edges"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    version_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_versions.id"), index=True
    )
    from_block_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_block_instances.id")
    )
    to_block_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_block_instances.id")
    )
    # Null = unconditional edge. Non-null, e.g. {"output_field": "is_valid", "equals": true}
    # — evaluated by the executor against the source block's output before following
    # this edge. Used by 조건분기 blocks; ignored by every other block type.
    condition: Mapped[dict | None] = mapped_column(JSON, nullable=True)
