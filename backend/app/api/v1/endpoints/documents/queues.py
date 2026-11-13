"""검토 대기와 실패 화면 전용 목록(작업 대기열).

문서 목록에 상태 필터만 건 화면은 "왜 멈췄는지"를 보여 주지 못한다. 이 모듈은
문서마다 멈춘 이유를 함께 모아 돌려준다.

- 검토 대기: 품질 검사 결과(점수, 경고 항목)와 승인을 기다리는 개인정보 탐지 건수
- 실패: 실패한 처리 단계, 실패 원인, 지금까지 실패한 횟수

권한 범위는 문서 목록과 같다(document_visibility_clause). 문서 수만큼 쿼리를 날리지
않도록 연관 정보는 문서 묶음 단위로 한 번씩 모아 온다.
"""
from collections import defaultdict
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user
from app.db.models.collection import Collection
from app.db.models.document import Document
from app.db.models.pii_detection import PiiDetection
from app.db.models.quality_report import QualityReport
from app.db.models.user import User
from app.db.models.workflow import WorkflowBlockInstance
from app.db.models.workflow_run import WorkflowRun, WorkflowRunStep
from app.db.session import get_db
from app.services.access_policy import (
    LIFECYCLE_SUPERSEDED,
    build_access_context,
    document_visibility_clause,
)

router = APIRouter()

# 한 화면에 모아 보여 줄 최대 건수. 넘으면 total로 알리고 오래된 것부터 보여 준다
_MAX_ITEMS = 200
# 품질 검사가 검토를 요구한 상태(quality_blocks._decide_review)
_QUALITY_REVIEW_STATUSES = ("FAILURE", "PARTIAL_FAILURE", "REVIEW_REQUIRED")


class ReviewQueueItem(BaseModel):
    document_id: UUID
    filename: str
    collection_id: UUID | None
    collection_name: str | None
    run_id: UUID | None
    waiting_since: datetime | None
    # quality: 품질 검사가 멈춤, pii: 개인정보 승인 대기, unknown: 기록된 이유가 없음
    reasons: list[str]
    quality_status: str | None
    overall_score: float | None
    warnings: list[str]
    warning_categories: list[str | None]
    pii_pending_count: int
    pii_entity_types: list[str]


class ReviewQueueResponse(BaseModel):
    total: int
    counts: dict[str, int]
    items: list[ReviewQueueItem]


class FailureQueueItem(BaseModel):
    document_id: UUID
    filename: str
    collection_id: UUID | None
    collection_name: str | None
    run_id: UUID | None
    failed_block_type: str | None
    error_code: str | None
    error_message: str | None
    failed_at: datetime | None
    failure_count: int
    can_retry: bool


class FailureQueueResponse(BaseModel):
    total: int
    items: list[FailureQueueItem]


async def _queue_documents(db: AsyncSession, user: User, status: str, limit: int):
    ctx = await build_access_context(db, user)
    filters = [
        document_visibility_clause(ctx),
        Document.status == status,
        Document.lifecycle_state != LIFECYCLE_SUPERSEDED,
    ]
    total = await db.scalar(select(func.count(Document.id)).where(*filters)) or 0
    documents = (
        await db.execute(
            select(Document).where(*filters).order_by(Document.updated_at.asc()).limit(limit)
        )
    ).scalars().all()
    # 가시성 조건 안의 하위 쿼리가 컬렉션 표를 참조하므로, 같은 쿼리에 컬렉션을 조인하면
    # 하위 쿼리가 바깥 쿼리로 묶여(auto-correlation) 깨진다. 이름은 따로 가져온다.
    collection_ids = {doc.collection_id for doc in documents if doc.collection_id}
    names = dict(
        (await db.execute(select(Collection.id, Collection.name).where(Collection.id.in_(collection_ids)))).all()
    ) if collection_ids else {}
    return total, [(doc, names.get(doc.collection_id)) for doc in documents]


@router.get("/review-queue", response_model=ReviewQueueResponse)
async def review_queue(
    limit: int = Query(_MAX_ITEMS, ge=1, le=_MAX_ITEMS),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """검토를 기다리는 문서와 멈춘 이유. 오래 기다린 문서가 먼저 온다."""
    total, rows = await _queue_documents(db, current_user, "WAITING_REVIEW", limit)
    run_ids = [doc.active_run_id for doc, _ in rows if doc.active_run_id]

    reports: dict = {}
    pii_counts: dict = defaultdict(int)
    pii_types: dict = defaultdict(set)
    if run_ids:
        for report in (
            await db.execute(
                select(QualityReport)
                .where(QualityReport.run_id.in_(run_ids))
                .order_by(QualityReport.created_at.asc())
            )
        ).scalars():
            reports[report.run_id] = report  # 같은 실행에 여러 개면 마지막 것
        for run_id, entity_type, count in (
            await db.execute(
                select(PiiDetection.run_id, PiiDetection.entity_type, func.count(PiiDetection.id))
                .where(
                    PiiDetection.run_id.in_(run_ids),
                    PiiDetection.approved_by.is_(None),
                    PiiDetection.rejected.is_(False),
                )
                .group_by(PiiDetection.run_id, PiiDetection.entity_type)
            )
        ).all():
            pii_counts[run_id] += count
            pii_types[run_id].add(entity_type)

    items: list[ReviewQueueItem] = []
    counts = {"quality": 0, "pii": 0, "unknown": 0}
    for doc, collection_name in rows:
        report = reports.get(doc.active_run_id)
        needs_quality = bool(report and report.status in _QUALITY_REVIEW_STATUSES and report.reviewed_at is None)
        pending_pii = pii_counts.get(doc.active_run_id, 0)
        reasons = [r for r, hit in (("quality", needs_quality), ("pii", pending_pii > 0)) if hit] or ["unknown"]
        for reason in reasons:
            counts[reason] += 1
        items.append(ReviewQueueItem(
            document_id=doc.id,
            filename=doc.original_filename or doc.filename,
            collection_id=doc.collection_id,
            collection_name=collection_name,
            run_id=doc.active_run_id,
            waiting_since=report.created_at if report else doc.updated_at,
            reasons=reasons,
            quality_status=report.status if report else None,
            overall_score=report.overall_score if report else None,
            warnings=[str(w) for w in (report.warnings or [])] if report else [],
            warning_categories=list(report.warning_categories or []) if report else [],
            pii_pending_count=pending_pii,
            pii_entity_types=sorted(pii_types.get(doc.active_run_id, set())),
        ))
    return ReviewQueueResponse(total=total, counts=counts, items=items)


@router.get("/failure-queue", response_model=FailureQueueResponse)
async def failure_queue(
    limit: int = Query(_MAX_ITEMS, ge=1, le=_MAX_ITEMS),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """처리에 실패한 문서와 실패한 단계, 원인, 실패 횟수. 오래된 실패가 먼저 온다."""
    total, rows = await _queue_documents(db, current_user, "FAILED", limit)
    doc_ids = [doc.id for doc, _ in rows]
    run_ids = [doc.active_run_id for doc, _ in rows if doc.active_run_id]

    runs: dict = {}
    failed_steps: dict = {}
    failure_counts: dict = {}
    if run_ids:
        for run in (await db.execute(select(WorkflowRun).where(WorkflowRun.id.in_(run_ids)))).scalars():
            runs[run.id] = run
        for step, block_type in (
            await db.execute(
                select(WorkflowRunStep, WorkflowBlockInstance.block_type)
                .join(WorkflowBlockInstance, WorkflowRunStep.block_instance_id == WorkflowBlockInstance.id)
                .where(WorkflowRunStep.run_id.in_(run_ids), WorkflowRunStep.status == "FAILED")
                .order_by(WorkflowRunStep.completed_at.asc())
            )
        ).all():
            failed_steps.setdefault(step.run_id, (step, block_type))  # 처음 실패한 단계가 원인
    if doc_ids:
        failure_counts = dict(
            (
                await db.execute(
                    select(WorkflowRun.document_id, func.count(WorkflowRun.id))
                    .where(WorkflowRun.document_id.in_(doc_ids), WorkflowRun.status == "FAILED")
                    .group_by(WorkflowRun.document_id)
                )
            ).all()
        )

    items: list[FailureQueueItem] = []
    for doc, collection_name in rows:
        run = runs.get(doc.active_run_id)
        step, block_type = failed_steps.get(doc.active_run_id, (None, None))
        items.append(FailureQueueItem(
            document_id=doc.id,
            filename=doc.original_filename or doc.filename,
            collection_id=doc.collection_id,
            collection_name=collection_name,
            run_id=doc.active_run_id,
            failed_block_type=block_type,
            error_code=step.error_code if step else None,
            error_message=(step.error_message if step else None)
            or (run.error_message if run else None)
            or doc.error_message,
            failed_at=(step.completed_at if step else None) or (run.completed_at if run else None) or doc.updated_at,
            failure_count=max(1, failure_counts.get(doc.id, 0)),
            # 일괄 재처리(batch-reprocess)는 실패한 단계가 기록된 실행에서만 이어 갈 수 있다
            can_retry=step is not None,
        ))
    return FailureQueueResponse(total=total, items=items)
