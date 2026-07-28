from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, Enum as SQLEnum, ForeignKey, Integer, String, Text
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
        SQLEnum(
            "QUEUED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED",
            # The quality_check block's review gate — see 통합 설계서 §7.4.
            "WAITING_REVIEW",
            name="workflow_run_status",
        ),
        default="QUEUED",
        index=True,
    )
    # What started this run — drives IA/UI labeling (통합 설계서 §3.8 처리 이력).
    trigger: Mapped[str] = mapped_column(
        SQLEnum(
            "UPLOAD", "MANUAL", "REPROCESS", "COLLECTION_REPROCESS",
            # 품질 검토 승인 후 자동으로 이어지는 분석 워크플로우 실행 — 통합
            # 설계서 §7.4, 마이그레이션 a3c5e7b9d1f2가 DB enum에 이 값을 추가.
            "AUTO_ANALYSIS",
            name="workflow_run_trigger",
        ),
        default="MANUAL",
        server_default="MANUAL",
    )
    # Non-null only for a partial reprocess run: the block this run starts
    # from, with everything upstream reused from the cache (§2.4/§8).
    started_block_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_block_instances.id", ondelete="SET NULL"), nullable=True
    )
    parent_run_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_runs.id", ondelete="SET NULL"), nullable=True
    )
    # Global dictionary_revisions version fixed at run start — dictionary
    # blocks read entries as of this version, not "latest" (§5 재현성).
    dictionary_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # {block_type: block_version, embedding_model, ...} — §16.2 처리 버전.
    version_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Partial-reprocess impact preview, computed at request time — §4.10/§15.3.
    impact: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # {block_type: timeoutSeconds} — per-run Celery hard-time-limit override,
    # read by the DAG executor ahead of the block's own persisted
    # config.timeoutSeconds. Set by reprocess_service.start_partial_reprocess
    # so a stuck run can be retried with a longer limit without mutating the
    # shared WorkflowBlockInstance.config (which other documents on the same
    # workflow version also use).
    timeout_overrides: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Set at upload time from the "검토 없이 진행" UI option — read by
    # quality_check (BlockContext.skip_review) to force review_policy to
    # auto_pass for this run only, without mutating the shared
    # WorkflowBlockInstance.config (9항목 펀치리스트 #1, 2026-07-24). Does NOT
    # bypass review for FAILURE/PARTIAL_FAILURE — those always require review
    # regardless of this flag.
    skip_review: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
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
        SQLEnum(
            "PENDING", "RUNNING", "COMPLETED", "FAILED",
            # A branch's untaken path, or a step served from cache without
            # actually running — see 통합 설계서 §4.1/§2.4.
            "SKIPPED",
            name="workflow_run_step_status",
        ),
        default="PENDING",
        index=True,
    )
    # Number of incoming edges that have fired so far. Only meaningful for 병합
    # blocks with >1 incoming edge — the executor enqueues this step once this
    # count reaches the block's total incoming-edge count (see tasks/workflow.py).
    completed_incoming_edges: Mapped[int] = mapped_column(Integer, default=0)
    input: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    input_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    output_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # MinIO artifacts-bucket key holding this step's large output payload
    # (structure tree, cleaned text, chunk list, ...) — DB keeps only a
    # summary in `output`. See §2.3.
    artifact_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    cached: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # One of the codes in §6 (FILE_UNSUPPORTED, OCR_FAILED, ...); null on
    # success or when the failure predates this error-code scheme.
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    warnings: Mapped[list | None] = mapped_column(JSON, nullable=True)
    metrics: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
