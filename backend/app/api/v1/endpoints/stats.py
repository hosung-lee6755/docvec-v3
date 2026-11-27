from datetime import datetime, timezone, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import and_, case, false, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user
from app.api.v1.permissions import accessible_collection_ids, check_project_access
from app.services.access_policy import LIFECYCLE_SUPERSEDED, build_access_context, document_visibility_clause
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
# 검토 대기: 워크플로우의 WAITING_REVIEW 와 옛 고정 파이프라인의 REVIEW_PENDING(화면 거르기 "검토대기" 와 같은 묶음)
_REVIEW_STATUSES = {"WAITING_REVIEW", "REVIEW_PENDING"}
_PROCESSING_STATS_WINDOW = timedelta(hours=24)
# 전처리 실행 뒤 자동으로 이어지는 분석 실행. 처리 한 번에 딸린 실행이라 처리 수로 세지 않는다
_ANALYSIS_TRIGGER = "AUTO_ANALYSIS"


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
    project_id: UUID | None = None,
):
    # Match list_documents visibility scope: include not only owned documents but
    # also documents in accessible (shared) collections. Filtering only created_by
    # would exclude shared collection documents and cause stats to undercount.
    # v3: 목록과 같은 가시성 조건(컬렉션 접근 + 보안등급 + 문서 ACL + 업로더 본인).
    # 문서 목록의 기본 보기처럼 이전 버전(superseded)은 세지 않고, project_id 를 주면 그 프로젝트 컬렉션만 센다.
    # 예전에는 프로젝트 문서 화면 요약 띠가 모든 프로젝트와 이전 버전까지 세어 "전체 70" 옆 목록이 26건이었다(2026-11-26)
    ctx = await build_access_context(db, current_user)
    shared_ids = ctx.collection_ids
    doc_scope = and_(document_visibility_clause(ctx), Document.lifecycle_state != LIFECYCLE_SUPERSEDED)
    if project_id is not None:
        await check_project_access(db, project_id, current_user, min_role="viewer")
        shared_ids = await accessible_collection_ids(db, current_user, project_id=project_id)
        doc_scope = and_(doc_scope, Document.collection_id.in_(shared_ids) if shared_ids else false())

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
    # 문서 화면 요약 띠도 이 값을 쓴다. 한 페이지만 세면 표시 건수에 따라 값이 달라졌다(2026-11-26)
    waiting_review = await db.scalar(
        select(func.count(Document.id)).where(doc_scope, Document.status.in_(_REVIEW_STATUSES))
    ) or 0
    failed = await db.scalar(
        select(func.count(Document.id)).where(doc_scope, Document.status == "FAILED")
    ) or 0
    collections = len(shared_ids)

    return {
        "total_documents": total_documents,
        "processing": processing,
        "indexed": indexed,
        "waiting_review": waiting_review,
        "failed": failed,
        "collections": collections,
    }


@router.get("/stats/processing", response_model=ProcessingStatsResponse)
async def get_processing_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """최근 24시간 처리 현황 — 와이어프레임 §9 위젯.

    문서 목록과 같은 가시성(document_visibility_clause)으로 센다. 예전에는 본인이 올린 문서만 세어, 관리자는 볼 수 있는
    문서 70건 가운데 본인 업로드 37건만 셌고 "검토 대기" 수가 사이드바 배지와 달랐다(2026-11-27). 검토 대기 수는 배지처럼
    이전 버전 문서를 빼고 센다.

    처리 한 번은 전처리 실행(업로드·수동·재처리)과 그 뒤 자동으로 이어지는 분석 실행(AUTO_ANALYSIS) 둘이다. 실패율·
    재처리율의 분모와 큐 대기는 전처리 실행으로 센다. 실행 수를 그대로 쓰면 재처리만 한 날도 재처리율이 50% 를 넘지
    못하고 실패율·큐 대기는 절반으로 나왔다. 실패는 두 실행 가운데 어느 쪽이 실패해도 그 처리의 실패다."""
    ctx = await build_access_context(db, current_user)
    visible = document_visibility_clause(ctx)
    since = datetime.now(timezone.utc).replace(tzinfo=None) - _PROCESSING_STATS_WINDOW

    runs_in_window = (
        select(WorkflowRun)
        .join(Document, WorkflowRun.document_id == Document.id)
        .where(visible, WorkflowRun.created_at >= since)
        .subquery()
    )
    is_processing = runs_in_window.c.trigger != _ANALYSIS_TRIGGER

    total_processings = await db.scalar(select(func.count(runs_in_window.c.id)).where(is_processing)) or 0
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
        .where(is_processing, runs_in_window.c.started_at.is_not(None))
    )

    # 기간 앞에서 시작한 처리의 분석 실행만 기간 안에 실패하면 분모보다 커질 수 있어 1 을 넘지 않게 한다
    failure_rate = min(failed_runs / total_processings, 1.0) if total_processings else 0.0
    reprocess_rate = reprocess_runs / total_processings if total_processings else 0.0

    avg_quality = await db.scalar(
        select(func.avg(QualityReport.overall_score))
        .select_from(QualityReport)
        .join(Document, QualityReport.document_id == Document.id)
        .where(visible, QualityReport.created_at >= since)
    )

    waiting_review_count = await db.scalar(
        select(func.count(Document.id)).where(
            visible, Document.lifecycle_state != LIFECYCLE_SUPERSEDED, Document.status == "WAITING_REVIEW"
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
            .where(visible, WorkflowRun.created_at >= since)
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
                visible,
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
