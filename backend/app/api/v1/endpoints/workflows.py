from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user
from app.api.v1.permissions import check_collection_access, check_document_access, check_project_access
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
from app.pipeline.blocks.registry import BLOCK_REGISTRY
from app.services.workflow_service import validate_graph

router = APIRouter()


class WorkflowCreate(BaseModel):
    project_id: UUID
    name: str
    description: str | None = None


class WorkflowResponse(BaseModel):
    id: UUID
    project_id: UUID
    name: str
    description: str | None
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class BlockIn(BaseModel):
    # Client-generated id so a fresh (unsaved) edge can reference a fresh
    # (unsaved) block before either has a real server-assigned id.
    id: UUID | str | None = None
    block_type: str
    label: str | None = None
    position: dict = {}
    config: dict = {}


class EdgeIn(BaseModel):
    from_block_id: UUID | str
    to_block_id: UUID | str
    condition: dict | None = None


class GraphUpdate(BaseModel):
    blocks: list[BlockIn]
    edges: list[EdgeIn]


class VersionResponse(BaseModel):
    id: UUID
    workflow_id: UUID
    version_number: int
    published_at: datetime | None
    created_at: datetime

    class Config:
        from_attributes = True


class RunCreate(BaseModel):
    version_id: UUID
    document_id: UUID | None = None
    collection_id: UUID | None = None


class RunResponse(BaseModel):
    id: UUID
    version_id: UUID
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    error_message: str | None
    created_at: datetime

    class Config:
        from_attributes = True


async def _get_workflow_or_404(db: AsyncSession, workflow_id: UUID) -> WorkflowDefinition:
    workflow = await db.get(WorkflowDefinition, workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return workflow


async def _get_version_or_404(db: AsyncSession, workflow_id: UUID, version_id: UUID) -> WorkflowVersion:
    version = await db.get(WorkflowVersion, version_id)
    if not version or str(version.workflow_id) != str(workflow_id):
        raise HTTPException(status_code=404, detail="Version not found")
    return version


async def _check_run_access(
    db: AsyncSession, workflow: WorkflowDefinition, run: WorkflowRun, user: User, min_role: str,
) -> None:
    """Project-scoped custom workflows check access via their project, same as
    every other workflow-definition endpoint. System-seeded workflows (the
    standard PREPROCESS pipeline every document upload runs) have
    project_id=None — check_project_access would 404 with "Project not
    found" for every one of their runs, which is the common case, not an
    edge case. Fall back to the run's document/collection access instead."""
    if workflow.project_id is not None:
        await check_project_access(db, workflow.project_id, user, min_role=min_role)
        return
    if run.document_id:
        doc = await db.get(Document, run.document_id)
        if doc is None:
            raise HTTPException(status_code=404, detail="Document not found")
        await check_document_access(db, doc, user, min_role=min_role)
        return
    if run.collection_id:
        await check_collection_access(db, run.collection_id, user, min_role=min_role)
        return
    raise HTTPException(status_code=403, detail="Access denied")


@router.get("/block-types")
async def list_block_types(current_user: User = Depends(get_current_user)):
    items = []
    for block_type, block_cls in BLOCK_REGISTRY.items():
        block = block_cls()
        schema = block.config_schema
        items.append({
            "block_type": block_type,
            "block_version": block.block_version,
            "category": block.category,
            "config_schema": schema.model_json_schema() if schema is not None else {},
        })
    return {"items": items}


@router.post("", response_model=WorkflowResponse)
async def create_workflow(
    data: WorkflowCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await check_project_access(db, data.project_id, current_user, min_role="editor")

    workflow = WorkflowDefinition(
        project_id=str(data.project_id),
        name=data.name,
        description=data.description,
        created_by=str(current_user.id),
    )
    db.add(workflow)
    await db.commit()
    await db.refresh(workflow)

    db.add(WorkflowVersion(workflow_id=workflow.id, version_number=1, created_by=str(current_user.id)))
    await db.commit()
    return workflow


@router.get("")
async def list_workflows(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await check_project_access(db, project_id, current_user, min_role="viewer")
    workflows = (
        await db.scalars(select(WorkflowDefinition).where(WorkflowDefinition.project_id == project_id))
    ).all()
    return {"items": [WorkflowResponse.model_validate(w) for w in workflows]}


@router.get("/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow(
    workflow_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    workflow = await _get_workflow_or_404(db, workflow_id)
    await check_project_access(db, workflow.project_id, current_user, min_role="viewer")
    return workflow


@router.delete("/{workflow_id}")
async def delete_workflow(
    workflow_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Deletes the workflow and everything under it (versions, blocks, edges,
    runs, run steps). No FK cascades are defined on these tables, so children
    are removed explicitly in dependency order before the definition row."""
    workflow = await _get_workflow_or_404(db, workflow_id)
    await check_project_access(db, workflow.project_id, current_user, min_role="editor")

    version_ids = (
        await db.scalars(
            select(WorkflowVersion.id).where(WorkflowVersion.workflow_id == workflow_id)
        )
    ).all()

    if version_ids:
        run_ids = (
            await db.scalars(
                select(WorkflowRun.id).where(WorkflowRun.version_id.in_(version_ids))
            )
        ).all()
        if run_ids:
            await db.execute(delete(WorkflowRunStep).where(WorkflowRunStep.run_id.in_(run_ids)))
            await db.execute(delete(WorkflowRun).where(WorkflowRun.id.in_(run_ids)))
        await db.execute(delete(WorkflowEdge).where(WorkflowEdge.version_id.in_(version_ids)))
        await db.execute(
            delete(WorkflowBlockInstance).where(WorkflowBlockInstance.version_id.in_(version_ids))
        )
        await db.execute(delete(WorkflowVersion).where(WorkflowVersion.id.in_(version_ids)))

    await db.delete(workflow)
    await db.commit()
    return {"deleted": True}


@router.get("/{workflow_id}/versions")
async def list_versions(
    workflow_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    workflow = await _get_workflow_or_404(db, workflow_id)
    await check_project_access(db, workflow.project_id, current_user, min_role="viewer")
    versions = (
        await db.scalars(
            select(WorkflowVersion)
            .where(WorkflowVersion.workflow_id == workflow_id)
            .order_by(WorkflowVersion.version_number.desc())
        )
    ).all()
    return {"items": [VersionResponse.model_validate(v) for v in versions]}


@router.post("/{workflow_id}/versions", response_model=VersionResponse)
async def create_draft_version(
    workflow_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Always creates a NEW draft version — never mutates a published one
    (활성 버전은 직접 수정하지 않고 새 버전으로 저장한다).

    Clones the latest version's blocks/edges into the new draft so editing
    continues from where the previous version left off, rather than
    starting from a blank canvas."""
    workflow = await _get_workflow_or_404(db, workflow_id)
    await check_project_access(db, workflow.project_id, current_user, min_role="editor")

    latest = await db.scalar(
        select(WorkflowVersion)
        .where(WorkflowVersion.workflow_id == workflow_id)
        .order_by(WorkflowVersion.version_number.desc())
    )
    next_number = (latest.version_number + 1) if latest else 1
    version = WorkflowVersion(
        workflow_id=workflow_id, version_number=next_number, created_by=str(current_user.id)
    )
    db.add(version)
    await db.flush()

    if latest is not None:
        source_blocks = (
            await db.scalars(
                select(WorkflowBlockInstance).where(WorkflowBlockInstance.version_id == latest.id)
            )
        ).all()
        source_edges = (
            await db.scalars(select(WorkflowEdge).where(WorkflowEdge.version_id == latest.id))
        ).all()

        id_map: dict[str, str] = {}
        for block in source_blocks:
            new_block = WorkflowBlockInstance(
                version_id=version.id,
                block_type=block.block_type,
                label=block.label,
                position=block.position,
                config=block.config,
            )
            db.add(new_block)
            await db.flush()
            id_map[str(block.id)] = str(new_block.id)

        for edge in source_edges:
            db.add(WorkflowEdge(
                version_id=version.id,
                from_block_id=id_map[str(edge.from_block_id)],
                to_block_id=id_map[str(edge.to_block_id)],
                condition=edge.condition,
            ))

    await db.commit()
    await db.refresh(version)
    return version


@router.delete("/{workflow_id}/versions/{version_id}")
async def delete_version(
    workflow_id: UUID,
    version_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Deletes one version and its children (blocks, edges, runs, run steps).
    The last remaining version cannot be deleted — delete the workflow itself
    instead."""
    workflow = await _get_workflow_or_404(db, workflow_id)
    await check_project_access(db, workflow.project_id, current_user, min_role="editor")
    version = await _get_version_or_404(db, workflow_id, version_id)

    version_count = len(
        (
            await db.scalars(
                select(WorkflowVersion.id).where(WorkflowVersion.workflow_id == workflow_id)
            )
        ).all()
    )
    if version_count <= 1:
        raise HTTPException(
            status_code=409,
            detail="마지막 남은 버전은 삭제할 수 없습니다. 워크플로우 자체를 삭제하세요.",
        )

    run_ids = (
        await db.scalars(select(WorkflowRun.id).where(WorkflowRun.version_id == version_id))
    ).all()
    if run_ids:
        await db.execute(delete(WorkflowRunStep).where(WorkflowRunStep.run_id.in_(run_ids)))
        await db.execute(delete(WorkflowRun).where(WorkflowRun.id.in_(run_ids)))
    await db.execute(delete(WorkflowEdge).where(WorkflowEdge.version_id == version_id))
    await db.execute(
        delete(WorkflowBlockInstance).where(WorkflowBlockInstance.version_id == version_id)
    )
    await db.delete(version)
    await db.commit()
    return {"deleted": True}


@router.get("/{workflow_id}/versions/{version_id}/graph")
async def get_graph(
    workflow_id: UUID,
    version_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    workflow = await _get_workflow_or_404(db, workflow_id)
    await check_project_access(db, workflow.project_id, current_user, min_role="viewer")
    await _get_version_or_404(db, workflow_id, version_id)

    blocks = (
        await db.scalars(
            select(WorkflowBlockInstance).where(WorkflowBlockInstance.version_id == version_id)
        )
    ).all()
    edges = (
        await db.scalars(select(WorkflowEdge).where(WorkflowEdge.version_id == version_id))
    ).all()
    return {
        "blocks": [
            {"id": b.id, "block_type": b.block_type, "label": b.label, "position": b.position, "config": b.config}
            for b in blocks
        ],
        "edges": [
            {"id": e.id, "from_block_id": e.from_block_id, "to_block_id": e.to_block_id, "condition": e.condition}
            for e in edges
        ],
    }


@router.put("/{workflow_id}/versions/{version_id}/graph")
async def update_graph(
    workflow_id: UUID,
    version_id: UUID,
    data: GraphUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Replaces this draft version's blocks/edges wholesale. Rejects the
    write if the version is already published — callers must create a new
    draft version (POST .../versions) instead."""
    workflow = await _get_workflow_or_404(db, workflow_id)
    await check_project_access(db, workflow.project_id, current_user, min_role="editor")
    version = await _get_version_or_404(db, workflow_id, version_id)
    if version.published_at is not None:
        raise HTTPException(status_code=409, detail="이미 게시된 버전은 수정할 수 없습니다. 새 버전을 생성하세요.")

    await db.execute(delete(WorkflowEdge).where(WorkflowEdge.version_id == version_id))
    await db.execute(delete(WorkflowBlockInstance).where(WorkflowBlockInstance.version_id == version_id))

    id_map: dict[str, str] = {}
    for block in data.blocks:
        row = WorkflowBlockInstance(
            version_id=version_id,
            block_type=block.block_type,
            label=block.label,
            position=block.position,
            config=block.config,
        )
        db.add(row)
        await db.flush()
        if block.id is not None:
            id_map[str(block.id)] = str(row.id)

    for edge in data.edges:
        db.add(WorkflowEdge(
            version_id=version_id,
            from_block_id=id_map.get(str(edge.from_block_id), str(edge.from_block_id)),
            to_block_id=id_map.get(str(edge.to_block_id), str(edge.to_block_id)),
            condition=edge.condition,
        ))

    await db.commit()
    errors = await validate_graph(db, str(version_id))
    return {"saved": True, "validation_errors": errors}


@router.post("/{workflow_id}/versions/{version_id}/publish")
async def publish_version(
    workflow_id: UUID,
    version_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    workflow = await _get_workflow_or_404(db, workflow_id)
    await check_project_access(db, workflow.project_id, current_user, min_role="editor")
    version = await _get_version_or_404(db, workflow_id, version_id)
    if version.published_at is not None:
        raise HTTPException(status_code=409, detail="이미 게시된 버전입니다")

    errors = await validate_graph(db, str(version_id))
    if errors:
        raise HTTPException(status_code=409, detail={"message": "워크플로우 유효성 검사 실패", "errors": errors})

    version.published_at = datetime.utcnow()
    workflow.status = "ACTIVE"
    await db.commit()
    return {"message": "게시되었습니다", "version_number": version.version_number}


# Fan-out safety cap for collection runs: each document becomes its own
# WorkflowRun, so an unbounded collection would flood the queue.
_MAX_COLLECTION_RUN_DOCUMENTS = 50


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
    workflow = await _get_workflow_or_404(db, workflow_id)
    await check_project_access(db, workflow.project_id, current_user, min_role="editor")
    version = await _get_version_or_404(db, workflow_id, data.version_id)
    if version.published_at is None:
        raise HTTPException(status_code=409, detail="게시되지 않은 버전은 실행할 수 없습니다")
    if not data.document_id and not data.collection_id:
        raise HTTPException(status_code=400, detail="실행 대상(문서 또는 컬렉션)을 지정하세요")

    errors = await validate_graph(db, str(data.version_id))
    if errors:
        raise HTTPException(status_code=409, detail={"message": "워크플로우 유효성 검사 실패", "errors": errors})

    if data.document_id:
        target_document_ids = [data.document_id]
    else:
        from app.db.models.document import Document

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

    from app.services.dictionary_service import current_dictionary_version

    dictionary_version = await current_dictionary_version(db)

    runs = []
    for document_id in target_document_ids:
        run = WorkflowRun(
            version_id=data.version_id,
            document_id=document_id,
            collection_id=data.collection_id,
            status="QUEUED",
            dictionary_version=dictionary_version,
        )
        db.add(run)
        runs.append(run)
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

    from app.pipeline.tasks.workflow import run_workflow_step

    for run in runs:
        for block in entry_blocks:
            timeout_seconds = (block.config or {}).get("timeoutSeconds", 300)
            run_workflow_step.apply_async(
                args=[str(run.id), str(block.id)], time_limit=timeout_seconds
            )

    return {
        "items": [RunResponse.model_validate(r) for r in runs],
        "count": len(runs),
    }


@router.get("/{workflow_id}/runs")
async def list_runs(
    workflow_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    workflow = await _get_workflow_or_404(db, workflow_id)
    await check_project_access(db, workflow.project_id, current_user, min_role="viewer")

    versions = (
        await db.scalars(select(WorkflowVersion).where(WorkflowVersion.workflow_id == workflow_id))
    ).all()
    version_numbers = {str(v.id): v.version_number for v in versions}
    runs = (
        await db.scalars(
            select(WorkflowRun)
            .where(WorkflowRun.version_id.in_([v.id for v in versions]))
            .order_by(WorkflowRun.created_at.desc())
        )
    ).all()

    from app.db.models.document import Document

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
    run = await db.get(WorkflowRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    version = await db.get(WorkflowVersion, run.version_id)
    workflow = await db.get(WorkflowDefinition, version.workflow_id)
    await _check_run_access(db, workflow, run, current_user, min_role="editor")

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
    run = await db.get(WorkflowRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    version = await db.get(WorkflowVersion, run.version_id)
    workflow = await db.get(WorkflowDefinition, version.workflow_id)
    await _check_run_access(db, workflow, run, current_user, min_role="editor")

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
    run = await db.get(WorkflowRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    version = await db.get(WorkflowVersion, run.version_id)
    workflow = await db.get(WorkflowDefinition, version.workflow_id)
    await _check_run_access(db, workflow, run, current_user, min_role="editor")

    if run.status not in ("WAITING_REVIEW", "QUEUED", "RUNNING"):
        raise HTTPException(status_code=409, detail="취소할 수 없는 상태입니다")

    run.status = "CANCELLED"
    run.completed_at = datetime.utcnow()
    if run.document_id:
        from app.db.models.document import Document

        doc = await db.get(Document, run.document_id)
        if doc is not None:
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
    run = await db.get(WorkflowRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    version = await db.get(WorkflowVersion, run.version_id)
    workflow = await db.get(WorkflowDefinition, version.workflow_id)
    await _check_run_access(db, workflow, run, current_user, min_role="viewer")

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
    run = await db.get(WorkflowRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    version = await db.get(WorkflowVersion, run.version_id)
    workflow = await db.get(WorkflowDefinition, version.workflow_id)
    await _check_run_access(db, workflow, run, current_user, min_role="viewer")

    steps = (
        await db.scalars(select(WorkflowRunStep).where(WorkflowRunStep.run_id == run_id))
    ).all()
    return {
        "run": RunResponse.model_validate(run),
        "steps": [
            {
                "id": s.id,
                "block_instance_id": s.block_instance_id,
                "status": s.status,
                "output": s.output,
                "error_message": s.error_message,
            }
            for s in steps
        ],
    }
