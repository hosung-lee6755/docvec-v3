"""워크플로우 버전(초안 생성·그래프 저장·게시·삭제) 엔드포인트."""
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user
from app.db.models.user import User
from app.db.models.workflow import WorkflowBlockInstance, WorkflowEdge, WorkflowVersion
from app.db.models.workflow_run import WorkflowRun, WorkflowRunStep
from app.db.session import get_db
from app.services.workflow_service import validate_graph

from .access import check_workflow_access, get_version_or_404, get_workflow_or_404
from .cloning import clone_graph
from .schemas import GraphUpdate, VersionResponse

router = APIRouter()


@router.get("/{workflow_id}/versions")
async def list_versions(
    workflow_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    workflow = await get_workflow_or_404(db, workflow_id)
    await check_workflow_access(db, workflow, current_user, min_role="viewer")
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
    workflow = await get_workflow_or_404(db, workflow_id)
    await check_workflow_access(db, workflow, current_user, min_role="editor")

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
        await clone_graph(db, latest.id, version.id)

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
    workflow = await get_workflow_or_404(db, workflow_id)
    await check_workflow_access(db, workflow, current_user, min_role="editor")
    version = await get_version_or_404(db, workflow_id, version_id)

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
    workflow = await get_workflow_or_404(db, workflow_id)
    await check_workflow_access(db, workflow, current_user, min_role="viewer")
    await get_version_or_404(db, workflow_id, version_id)

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
    workflow = await get_workflow_or_404(db, workflow_id)
    await check_workflow_access(db, workflow, current_user, min_role="editor")
    version = await get_version_or_404(db, workflow_id, version_id)
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
    workflow = await get_workflow_or_404(db, workflow_id)
    await check_workflow_access(db, workflow, current_user, min_role="editor")
    version = await get_version_or_404(db, workflow_id, version_id)
    if version.published_at is not None:
        raise HTTPException(status_code=409, detail="이미 게시된 버전입니다")

    errors = await validate_graph(db, str(version_id))
    if errors:
        raise HTTPException(status_code=409, detail={"message": "워크플로우 유효성 검사 실패", "errors": errors})

    version.published_at = datetime.now(timezone.utc).replace(tzinfo=None)
    workflow.status = "ACTIVE"
    await db.commit()
    return {"message": "게시되었습니다", "version_number": version.version_number}
