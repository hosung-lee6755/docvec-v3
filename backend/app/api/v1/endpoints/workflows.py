from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user
from app.api.v1.permissions import check_project_access
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


@router.get("/block-types")
async def list_block_types(current_user: User = Depends(get_current_user)):
    return {"items": list(BLOCK_REGISTRY.keys())}


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
    (활성 버전은 직접 수정하지 않고 새 버전으로 저장한다)."""
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
    await db.commit()
    await db.refresh(version)
    return version


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


@router.post("/{workflow_id}/run", response_model=RunResponse)
async def run_workflow(
    workflow_id: UUID,
    data: RunCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    workflow = await _get_workflow_or_404(db, workflow_id)
    await check_project_access(db, workflow.project_id, current_user, min_role="editor")
    version = await _get_version_or_404(db, workflow_id, data.version_id)
    if version.published_at is None:
        raise HTTPException(status_code=409, detail="게시되지 않은 버전은 실행할 수 없습니다")

    errors = await validate_graph(db, str(data.version_id))
    if errors:
        raise HTTPException(status_code=409, detail={"message": "워크플로우 유효성 검사 실패", "errors": errors})

    run = WorkflowRun(
        version_id=data.version_id,
        document_id=data.document_id,
        collection_id=data.collection_id,
        status="QUEUED",
    )
    db.add(run)
    await db.commit()
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

    for block in entry_blocks:
        run_workflow_step.delay(str(run.id), str(block.id))

    return run


@router.get("/{workflow_id}/runs")
async def list_runs(
    workflow_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    workflow = await _get_workflow_or_404(db, workflow_id)
    await check_project_access(db, workflow.project_id, current_user, min_role="viewer")

    version_ids = (
        await db.scalars(select(WorkflowVersion.id).where(WorkflowVersion.workflow_id == workflow_id))
    ).all()
    runs = (
        await db.scalars(
            select(WorkflowRun)
            .where(WorkflowRun.version_id.in_(version_ids))
            .order_by(WorkflowRun.created_at.desc())
        )
    ).all()
    return {"items": [RunResponse.model_validate(r) for r in runs]}


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
    await check_project_access(db, workflow.project_id, current_user, min_role="viewer")

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
