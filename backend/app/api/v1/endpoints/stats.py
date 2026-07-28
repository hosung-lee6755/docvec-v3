from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user
from app.api.v1.permissions import accessible_collection_ids
from app.db.models.collection import Collection
from app.db.models.document import Document
from app.db.models.quality_report import QualityReport
from app.db.models.user import User
from app.db.models.workflow import WorkflowBlockInstance
from app.db.models.workflow_run import WorkflowRun, WorkflowRunStep
from app.db.session import get_db

router = APIRouter()

# document_status DB enum(app/db/models/document.py)의 처리중 상태 전부를 반영해야
# 한다 — VALIDATING/MASKING/STRUCTURING/NORMALIZING(DAG 워크플로우 엔진 도입분)이
# 빠져 있어 대시보드 카드(/stats)가 목록(프런트 PROCESSING_STATUSES)보다 적게
# 세는 불일치가 있었다.
_PROCESSING_STATUSES = {
    "QUEUED", "INGESTING", "PARSING", "STRUCTURING", "NORMALIZING",
    "CHUNKING", "EMBEDDING", "UPLOADING", "VALIDATING", "MASKING",
}
_PROCESSING_STATS_WINDOW = timedelta(hours=24)


class BlockStat(BaseModel):
    block_type: str
    execution_count: int
    failure_rate: float
    avg_duration_seconds: float | None


class RecentFailure(BaseModel):
    document_id: str
    filename: str
    error_message: str | None
    created_at: datetime


class ProcessingStatsResponse(BaseModel):
    processed_documents: int
    avg_quality: float | None
    failure_rate: float
    reprocess_rate: float
    waiting_review_count: int
    avg_queue_seconds: float | None
    block_stats: list[BlockStat]
    recent_failures: list[RecentFailure]


@router.get("/stats")
async def get_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # list_documents(documents.py)가 쓰는 것과 동일한 가시성 범위 — "내가 만든 문서"만이
    # 아니라 "내가 접근 가능한 컬렉션의 문서"까지 포함해야 한다. 이전엔 created_by만
    # 필터링해 대시보드 카드가 목록(공유 컬렉션 문서 포함)보다 적게 세는 불일치가
    # 있었다.
    shared_ids = await accessible_collection_ids(db, current_user)
    owned_or_shared = [Document.created_by == str(current_user.id)]
    if shared_ids:
        owned_or_shared.append(Document.collection_id.in_(shared_ids))
    doc_scope = or_(*owned_or_shared)

    total_documents = await db.scalar(
        select(func.count(Document.id)).where(doc_scope)
    ) or 0
    processing = await db.scalar(
        select(func.count(Document.id)).where(
            doc_scope,
            Document.status.in_(_PROCESSING_STATUSES),
        )
    ) or 0
    indexed = await db.scalar(
        select(func.count(Document.id)).where(
            doc_scope,
            Document.status == "INDEXED",
        )
    ) or 0
    collections = len(shared_ids)

    return {
        "total_documents": total_documents,
        "processing": processing,
        "indexed": indexed,
        "collections": collections,
    }


@router.get("/stats/processing", response_model=ProcessingStatsResponse)
async def get_processing_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """최근 24시간 처리 현황 — 와이어프레임 §9 위젯. 관리자 전용이 아니라 /stats와
    동일하게 current_user 소유 문서로 스코프한다(§0: '문서 처리' 그룹, 관리 그룹 아님)."""
    user_id = str(current_user.id)
    since = datetime.utcnow() - _PROCESSING_STATS_WINDOW

    runs_in_window = (
        select(WorkflowRun)
        .join(Document, WorkflowRun.document_id == Document.id)
        .where(Document.created_by == user_id, WorkflowRun.created_at >= since)
        .subquery()
    )

    total_runs = await db.scalar(select(func.count(runs_in_window.c.id))) or 0
    processed_documents = await db.scalar(
        select(func.count(func.distinct(runs_in_window.c.document_id))).where(
            runs_in_window.c.status == "COMPLETED"
        )
    ) or 0
    failed_runs = await db.scalar(
        select(func.count(runs_in_window.c.id)).where(runs_in_window.c.status == "FAILED")
    ) or 0
    reprocess_runs = await db.scalar(
        select(func.count(runs_in_window.c.id)).where(
            runs_in_window.c.trigger.in_(("REPROCESS", "COLLECTION_REPROCESS"))
        )
    ) or 0
    avg_queue_seconds = await db.scalar(
        select(func.avg(func.extract("epoch", runs_in_window.c.started_at - runs_in_window.c.created_at)))
        .where(runs_in_window.c.started_at.is_not(None))
    )

    failure_rate = failed_runs / total_runs if total_runs else 0.0
    reprocess_rate = reprocess_runs / total_runs if total_runs else 0.0

    avg_quality = await db.scalar(
        select(func.avg(QualityReport.overall_score))
        .select_from(QualityReport)
        .join(Document, QualityReport.document_id == Document.id)
        .where(Document.created_by == user_id, QualityReport.created_at >= since)
    )

    waiting_review_count = await db.scalar(
        select(func.count(Document.id)).where(
            Document.created_by == user_id, Document.status == "WAITING_REVIEW"
        )
    ) or 0

    block_rows = (
        await db.execute(
            select(
                WorkflowBlockInstance.block_type,
                func.count(WorkflowRunStep.id).label("execution_count"),
                func.sum(case((WorkflowRunStep.status == "FAILED", 1), else_=0)).label("failure_count"),
                func.avg(
                    func.extract("epoch", WorkflowRunStep.completed_at - WorkflowRunStep.started_at)
                ).label("avg_duration_seconds"),
            )
            .select_from(WorkflowRunStep)
            .join(WorkflowRun, WorkflowRunStep.run_id == WorkflowRun.id)
            .join(Document, WorkflowRun.document_id == Document.id)
            .join(WorkflowBlockInstance, WorkflowRunStep.block_instance_id == WorkflowBlockInstance.id)
            .where(Document.created_by == user_id, WorkflowRun.created_at >= since)
            .group_by(WorkflowBlockInstance.block_type)
        )
    ).all()
    block_stats = [
        BlockStat(
            block_type=row.block_type,
            execution_count=row.execution_count,
            failure_rate=(row.failure_count / row.execution_count) if row.execution_count else 0.0,
            avg_duration_seconds=row.avg_duration_seconds,
        )
        for row in block_rows
    ]

    failure_rows = (
        await db.execute(
            select(WorkflowRun.document_id, Document.filename, WorkflowRun.error_message, WorkflowRun.created_at)
            .select_from(WorkflowRun)
            .join(Document, WorkflowRun.document_id == Document.id)
            .where(
                Document.created_by == user_id,
                WorkflowRun.status == "FAILED",
                WorkflowRun.created_at >= since,
            )
            .order_by(WorkflowRun.created_at.desc())
            .limit(5)
        )
    ).all()
    recent_failures = [
        RecentFailure(
            document_id=str(row.document_id),
            filename=row.filename,
            error_message=row.error_message,
            created_at=row.created_at,
        )
        for row in failure_rows
    ]

    return ProcessingStatsResponse(
        processed_documents=processed_documents,
        avg_quality=avg_quality,
        failure_rate=failure_rate,
        reprocess_rate=reprocess_rate,
        waiting_review_count=waiting_review_count,
        avg_queue_seconds=avg_queue_seconds,
        block_stats=block_stats,
        recent_failures=recent_failures,
    )
