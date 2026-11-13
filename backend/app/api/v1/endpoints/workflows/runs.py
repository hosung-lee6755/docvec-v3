"""워크플로우 실행(시작·목록·검토 재개/반려·내보내기·조회·삭제) 엔드포인트."""
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import and_, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user
from app.api.v1.permissions import (
    check_collection_access,
    check_document_access,
)
from app.db.models.document import Document
from app.db.models.user import User
from app.db.models.workflow import (
    WorkflowBlockInstance,
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowVersion,
)
from app.db.models.workflow_run import WorkflowRun, WorkflowRunStep
from app.db.session import get_db
from app.services.workflow_service import validate_graph

from .access import (
    check_run_access,
    check_workflow_access,
    get_version_or_404,
    get_workflow_or_404,
)
from .schemas import RunCreate, RunResponse

router = APIRouter()

# Fan-out safety cap for collection runs: each document becomes its own
# WorkflowRun, so an unbounded collection would flood the queue.
_MAX_COLLECTION_RUN_DOCUMENTS = 50
# 진행 중으로 보는 run 상태 (app.pipeline.tasks.workflow._LIVE_RUN_STATUSES 와 같은 값 —
# API 모듈이 Celery 태스크 모듈을 import 하지 않도록 따로 둔다).
_LIVE_RUN_STATUSES = ("QUEUED", "RUNNING", "WAITING_REVIEW")


async def _load_run_context(
    db: AsyncSession, run_id: UUID
) -> tuple[WorkflowRun, WorkflowVersion, WorkflowDefinition]:
    """run → version → workflow 를 읽는다. run이 없으면 404."""
    run = await db.get(WorkflowRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    version = await db.get(WorkflowVersion, run.version_id)
    workflow = await db.get(WorkflowDefinition, version.workflow_id)
    return run, version, workflow


async def _check_run_target_access(db: AsyncSession, data: RunCreate, user: User) -> None:
    """워크플로우 편집 권한과 별개로, 실행 대상 문서/컬렉션에 대한 editor 권한을 요구한다.
    실행은 문서 상태와 분석 결과를 바꾸고 결과를 `/runs/{id}` 로 읽을 수 있게 하므로, 이 검사가
    없으면 자기 워크플로우로 남의 문서를 실행해 파싱 텍스트를 읽을 수 있다."""
    if data.document_id:
        doc = await db.get(Document, data.document_id)
        if doc is None:
            raise HTTPException(status_code=404, detail="Document not found")
        await check_document_access(db, doc, user, min_role="editor")
    else:
        await check_collection_access(db, data.collection_id, user, min_role="editor")


async def _points_at_other_live_run(db: AsyncSession, doc: Document, run: WorkflowRun) -> bool:
    """문서가 다른 진행 중 run 을 가리키면(재처리 등) 옛 run 의 취소가 문서 상태를 덮어쓰면 안 된다.
    워커의 `_fail_document` 와 같은 가드다."""
    if doc.active_run_id is None or str(doc.active_run_id) == str(run.id):
        return False
    other = await db.get(WorkflowRun, doc.active_run_id)
    return other is not None and other.status in _LIVE_RUN_STATUSES


async def _idle_documents(db: AsyncSession, document_ids: list) -> list[Document]:
    """처리 중인 run이 없는 문서만 순서대로 돌려준다. 같은 문서에 run 두 개가 동시에 돌면
    서로의 청크를 지우고 상태를 덮어쓰므로, 진행 중인 문서는 이번 실행에서 뺀다."""
    docs = (await db.scalars(select(Document).where(Document.id.in_(document_ids)))).all()
    by_id = {str(d.id): d for d in docs}
    active_ids = [d.active_run_id for d in docs if d.active_run_id is not None]
    live = set()
    if active_ids:
        live = {
            str(run_id) for run_id in (await db.scalars(
                select(WorkflowRun.id).where(
                    WorkflowRun.id.in_(active_ids), WorkflowRun.status.in_(_LIVE_RUN_STATUSES))
            )).all()
        }
    return [
        by_id[str(i)] for i in document_ids
        if str(i) in by_id and str(by_id[str(i)].active_run_id) not in live
    ]


async def _restrict_to_accessible_runs(db: AsyncSession, query, user: User):
    """문서 목록과 같은 기준(v3): 문서 실행은 그 문서를 볼 수 있을 때(업로더·등급·ACL),
    문서 없는 컬렉션 단위 실행은 그 컬렉션에 접근할 수 있을 때만 보인다 — 실행 기록에는
    문서 파일명이 실리므로 숨겨진 문서의 존재가 새지 않게 한다."""
    from app.services.access_policy import build_access_context, document_visibility_clause

    ctx = await build_access_context(db, user)
    visible = or_(
        and_(WorkflowRun.document_id.is_not(None), document_visibility_clause(ctx)),
        and_(
            WorkflowRun.document_id.is_(None),
            WorkflowRun.collection_id.in_(sorted(ctx.collection_ids)),
        ),
    )
    return query.outerjoin(Document, Document.id == WorkflowRun.document_id).where(visible)


@router.post("/{workflow_id}/run")
async def run_workflow(
    workflow_id: UUID,
    data: RunCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Starts one run per target document. A document_id targets that one
    document; a collection_id fans out into one run per parsed document in
    the collection (capped at _MAX_COLLECTION_RUN_DOCUMENTS)."""
    workflow = await get_workflow_or_404(db, workflow_id)
    await check_workflow_access(db, workflow, current_user, min_role="editor")
    version = await get_version_or_404(db, workflow_id, data.version_id)
    if version.published_at is None:
        raise HTTPException(status_code=409, detail="게시되지 않은 버전은 실행할 수 없습니다")
    if not data.document_id and not data.collection_id:
        raise HTTPException(status_code=400, detail="실행 대상(문서 또는 컬렉션)을 지정하세요")

    errors = await validate_graph(db, str(data.version_id))
    if errors:
        raise HTTPException(status_code=409, detail={"message": "워크플로우 유효성 검사 실패", "errors": errors})
    await _check_run_target_access(db, data, current_user)

    if data.document_id:
        target_document_ids = [data.document_id]
    else:
        target_document_ids = (
            await db.scalars(
                select(Document.id)
                .where(
                    Document.collection_id == data.collection_id,
                    Document.parsed_text.is_not(None),
                )
                .order_by(Document.created_at)
                .limit(_MAX_COLLECTION_RUN_DOCUMENTS)
            )
        ).all()
        if not target_document_ids:
            raise HTTPException(
                status_code=409,
                detail="컬렉션에 파싱 완료된 문서가 없습니다",
            )

    documents = await _idle_documents(db, target_document_ids)
    skipped_in_progress = len(target_document_ids) - len(documents)
    if not documents:
        raise HTTPException(
            status_code=409,
            detail="대상 문서가 아직 처리 중입니다. 지금 진행 중인 처리가 끝난 뒤 다시 실행하세요.",
        )

    from app.services.dictionary_service import current_dictionary_version

    dictionary_version = await current_dictionary_version(db)

    runs = []
    for doc in documents:
        run = WorkflowRun(
            version_id=data.version_id,
            document_id=doc.id,
            collection_id=data.collection_id,
            status="QUEUED",
            dictionary_version=dictionary_version,
        )
        db.add(run)
        runs.append(run)
    # documents.active_run_id ↔ workflow_runs.document_id 외래키가 순환이라 run을 먼저 내보낸다
    # (reprocess_service, 분석 자동 실행과 같은 순서).
    await db.flush()
    for doc, run in zip(documents, runs):
        # 업로드·재처리·분석 자동 실행처럼 문서는 늘 최신 run을 가리킨다. 옮기지 않으면 품질 보고서,
        # 검토/실패 대기열, 부분 재처리가 이 run의 rag_store가 청크를 지운 옛 run을 기준으로 삼는다.
        doc.active_run_id = run.id
    await db.commit()
    for run in runs:
        await db.refresh(run)

    blocks = (
        await db.scalars(
            select(WorkflowBlockInstance).where(WorkflowBlockInstance.version_id == data.version_id)
        )
    ).all()
    edges = (
        await db.scalars(select(WorkflowEdge).where(WorkflowEdge.version_id == data.version_id))
    ).all()
    has_incoming = {e.to_block_id for e in edges}
    entry_blocks = [b for b in blocks if b.id not in has_incoming]

    from app.pipeline.tasks.workflow import run_workflow_step, step_queue_for_block

    for run in runs:
        for block in entry_blocks:
            timeout_seconds = (block.config or {}).get("timeoutSeconds", 1800)
            run_workflow_step.apply_async(
                args=[str(run.id), str(block.id)], time_limit=timeout_seconds,
                queue=step_queue_for_block(block),
            )

    return {
        "items": [RunResponse.model_validate(r) for r in runs],
        "count": len(runs),
        "skipped_in_progress": skipped_in_progress,
    }


@router.get("/{workflow_id}/runs")
async def list_runs(
    workflow_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    workflow = await get_workflow_or_404(db, workflow_id)
    await check_workflow_access(db, workflow, current_user, min_role="viewer")

    versions = (
        await db.scalars(select(WorkflowVersion).where(WorkflowVersion.workflow_id == workflow_id))
    ).all()
    version_numbers = {str(v.id): v.version_number for v in versions}
    query = (
        select(WorkflowRun)
        .where(WorkflowRun.version_id.in_([v.id for v in versions]))
        .order_by(WorkflowRun.created_at.desc())
    )
    if workflow.project_id is None and current_user.role != "admin":
        # 시스템 워크플로우는 모든 사용자가 조회할 수 있지만, 실행 기록에는 다른 사용자의
        # 문서 파일명이 들어 있다. 본인이 접근할 수 있는 문서/컬렉션의 실행만 보여준다.
        query = await _restrict_to_accessible_runs(db, query, current_user)
    runs = (await db.scalars(query)).all()

    doc_ids = {run.document_id for run in runs if run.document_id}
    doc_names: dict[str, str] = {}
    if doc_ids:
        docs = (await db.scalars(select(Document).where(Document.id.in_(doc_ids)))).all()
        doc_names = {str(d.id): d.original_filename for d in docs}

    items = []
    for run in runs:
        item = RunResponse.model_validate(run).model_dump()
        item["version_number"] = version_numbers.get(str(run.version_id))
        item["document_id"] = run.document_id
        item["collection_id"] = run.collection_id
        item["document_filename"] = doc_names.get(str(run.document_id)) if run.document_id else None
        items.append(item)
    return {"items": items}


@router.delete("/runs/{run_id}")
async def delete_run(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Deletes one run record and its step outputs. Running/queued runs are
    protected — they would keep writing steps after the delete."""
    run, _version, workflow = await _load_run_context(db, run_id)
    await check_run_access(db, workflow, run, current_user, min_role="editor")

    if run.status in ("QUEUED", "RUNNING"):
        raise HTTPException(status_code=409, detail="실행 중인 기록은 삭제할 수 없습니다")

    await db.execute(delete(WorkflowRunStep).where(WorkflowRunStep.run_id == run_id))
    await db.delete(run)
    await db.commit()
    return {"deleted": True}


@router.post("/runs/{run_id}/resume")
async def resume_run(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Resumes a run paused at a review gate (설계서 §7.4, case a/b — 승인 /
    수정 후 승인). Validation happens here; the actual DAG-walking runs in the
    Celery task `resume_workflow_run` against the sync session executor code
    already uses."""
    run, _version, workflow = await _load_run_context(db, run_id)
    await check_run_access(db, workflow, run, current_user, min_role="editor")

    if run.status != "WAITING_REVIEW":
        raise HTTPException(status_code=409, detail="검토 대기 상태가 아닙니다")

    from app.pipeline.tasks.workflow import resume_workflow_run

    resume_workflow_run.delay(str(run_id))
    return {"status": "RESUME_QUEUED"}


@router.post("/runs/{run_id}/cancel")
async def cancel_run(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Rejects a run at a review gate (설계서 §7.4, case c — 반려). The run is
    marked CANCELLED and its target document FAILED so the reason is visible
    on the document detail screen."""
    run, _version, workflow = await _load_run_context(db, run_id)
    await check_run_access(db, workflow, run, current_user, min_role="editor")

    if run.status not in ("WAITING_REVIEW", "QUEUED", "RUNNING"):
        raise HTTPException(status_code=409, detail="취소할 수 없는 상태입니다")

    run.status = "CANCELLED"
    run.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    if run.document_id:
        doc = await db.get(Document, run.document_id)
        if doc is not None and not await _points_at_other_live_run(db, doc, run):
            doc.status = "FAILED"
            doc.error_message = "사용자가 검토를 반려하여 처리가 취소되었습니다"
    await db.commit()
    return {"status": "CANCELLED"}


@router.get("/runs/{run_id}/export")
async def export_run(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Downloads the run's final result (every terminal/output step's output,
    plus per-step outputs) as a JSON attachment."""
    run, version, workflow = await _load_run_context(db, run_id)
    await check_run_access(db, workflow, run, current_user, min_role="viewer")

    steps = (
        await db.scalars(select(WorkflowRunStep).where(WorkflowRunStep.run_id == run_id))
    ).all()
    blocks_by_id = {
        str(b.id): b
        for b in (
            await db.scalars(
                select(WorkflowBlockInstance).where(WorkflowBlockInstance.version_id == run.version_id)
            )
        ).all()
    }
    final_outputs = [
        (s.output or {})
        for s in steps
        if blocks_by_id.get(str(s.block_instance_id)) is not None
        and blocks_by_id[str(s.block_instance_id)].block_type == "output"
        and s.status == "COMPLETED"
    ]
    payload = {
        "run_id": str(run.id),
        "workflow": workflow.name,
        "version_number": version.version_number,
        "status": run.status,
        "document_id": str(run.document_id) if run.document_id else None,
        "collection_id": str(run.collection_id) if run.collection_id else None,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "result": final_outputs[0] if len(final_outputs) == 1 else final_outputs,
        "steps": [
            {
                "block": (
                    blocks_by_id[str(s.block_instance_id)].label
                    or blocks_by_id[str(s.block_instance_id)].block_type
                )
                if str(s.block_instance_id) in blocks_by_id
                else str(s.block_instance_id),
                "status": s.status,
                "output": s.output,
                "error_message": s.error_message,
            }
            for s in steps
        ],
    }
    return JSONResponse(
        content=jsonable_encoder(payload),
        headers={"Content-Disposition": f'attachment; filename="workflow-run-{run_id}.json"'},
    )


@router.get("/runs/{run_id}")
async def get_run(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    run, _version, workflow = await _load_run_context(db, run_id)
    await check_run_access(db, workflow, run, current_user, min_role="viewer")

    steps = (
        await db.scalars(select(WorkflowRunStep).where(WorkflowRunStep.run_id == run_id))
    ).all()
    from app.pipeline.blocks.registry import BLOCK_TYPE_LABELS

    blocks = (
        await db.scalars(
            select(WorkflowBlockInstance).where(WorkflowBlockInstance.version_id == run.version_id)
        )
    ).all()
    blocks_by_id = {str(b.id): b for b in blocks}

    def _step_display(s: WorkflowRunStep) -> dict:
        block = blocks_by_id.get(str(s.block_instance_id))
        block_type = block.block_type if block else None
        label = (block.label if block else None) or BLOCK_TYPE_LABELS.get(block_type, block_type)
        return {
            "id": s.id,
            "block_instance_id": s.block_instance_id,
            "block_type": block_type,
            "label": label,
            "status": s.status,
            "output": s.output,
            "error_message": s.error_message,
            "cached": s.cached,
            "warnings": s.warnings,
        }

    return {
        "run": RunResponse.model_validate(run),
        "steps": [_step_display(s) for s in steps],
    }
