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

# Must reflect all processing states from the document_status DB enum
# (app/db/models/document.py), including VALIDATING, MASKING, STRUCTURING,
# NORMALIZING, and ANALYZING (컬렉션 기본 분석 워크플로우 자동 실행, 2026-07-29
# 도입). Omitting any state causes this stat tile to undercount vs.
# frontend/src/lib/documentStatus.ts's PROCESSING_STATUSES — ANALYZING was
# missing here, so the dashboard's "처리 중" stat tile and the "처리 중인
# 작업" widget (which queries /documents with the frontend list) diverged
# whenever any document was ANALYZING (실측 확인, 2026-07-30).
_PROCESSING_STATUSES = {
    "QUEUED", "INGESTING", "PARSING", "STRUCTURING", "NORMALIZING",
    "CHUNKING", "EMBEDDING", "UPLOADING", "VALIDATING", "MASKING", "ANALYZING",
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
    # Match list_documents visibility scope: include not only owned documents but
    # also documents in accessible (shared) collections. Filtering only created_by
    # would exclude shared collection documents and cause stats to undercount.
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
                # 브로커 재전송으로 이미 끝난 step에 중복 실행이 들어오면
                # started_at이 completed_at보다 뒤로 밀려 음수 처리시간이
                # 나올 수 있다(처리현황 블록별 평균시간에서 확인, 2026-07-30;
                # 근본 원인은 run_workflow_step의 재진입 가드로 막았지만,
                # 이 평균 계산 자체도 그런 이상치를 침묵 반영하지 않도록
                # 방어한다). 이상치는 평균에서 제외(NULL)한다 — AVG는 NULL을
                # 무시하므로 execution_count/failure_count 집계는 영향 없다.
                func.avg(
                    case(
                        (
                            WorkflowRunStep.completed_at >= WorkflowRunStep.started_at,
                            func.extract("epoch", WorkflowRunStep.completed_at - WorkflowRunStep.started_at),
                        ),
                        else_=None,
                    )
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
