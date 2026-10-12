"""워크플로우 정의(목록·생성·수정·복제·삭제)와 블록 타입 목록 엔드포인트."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user
from app.api.v1.permissions import accessible_project_ids, check_project_access
from app.db.models.collection import Collection
from app.db.models.project import Project
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

from .access import check_workflow_access, get_workflow_or_404
from .cloning import clone_graph
from .schemas import (
    WorkflowCreate,
    WorkflowDuplicate,
    WorkflowListItem,
    WorkflowResponse,
    WorkflowStatusUpdate,
)

router = APIRouter()


@router.get("/block-types")
async def list_block_types(current_user: User = Depends(get_current_user)):
    from app.pipeline.blocks.registry import BLOCK_TYPE_LABELS

    items = []
    for block_type, block_cls in BLOCK_REGISTRY.items():
        block = block_cls()
        schema = block.config_schema
        items.append({
            "block_type": block_type,
            "block_version": block.block_version,
            "category": block.category,
            "label": BLOCK_TYPE_LABELS.get(block_type, block_type),
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
        kind=data.kind,
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
    project_id: UUID | None = None,
    kind: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Project-owned workflows plus the system-seeded standard PREPROCESS
    workflow (project_id is None) — the mockup's 워크플로우 목록 screen shows
    the system default alongside project workflows with a locked '★ 시스템
    기본' marker (§9), since every project can select it even though it has
    no project of its own.

    When project_id is omitted, this returns workflows across every project
    the caller can access (same cross-project pattern as list_collections in
    collections.py) plus the system default, so the top-level 워크플로우 nav
    item shows a real list instead of forcing a project pick first."""
    if project_id is not None:
        await check_project_access(db, project_id, current_user, min_role="viewer")
        scoped_project_ids = [str(project_id)]
        query = select(WorkflowDefinition).where(
            (WorkflowDefinition.project_id == project_id) | (WorkflowDefinition.project_id.is_(None))
        )
    else:
        scoped_project_ids = await accessible_project_ids(db, current_user)
        query = select(WorkflowDefinition).where(
            (WorkflowDefinition.project_id.in_(scoped_project_ids)) | (WorkflowDefinition.project_id.is_(None))
        )
    if kind is not None:
        query = query.where(WorkflowDefinition.kind == kind)
    workflows = (await db.scalars(query)).all()

    user_ids = {w.created_by for w in workflows}
    usernames: dict[str, str] = {}
    if user_ids:
        users = (await db.scalars(select(User).where(User.id.in_(user_ids)))).all()
        usernames = {str(u.id): u.username for u in users}

    project_names: dict[str, str] = {}
    workflow_project_ids = {str(w.project_id) for w in workflows if w.project_id is not None}
    if workflow_project_ids:
        rows = (
            await db.execute(select(Project.id, Project.name).where(Project.id.in_(workflow_project_ids)))
        ).all()
        project_names = {str(row[0]): row[1] for row in rows}

    default_counts: dict[str, int] = {}
    latest_versions: dict[str, int] = {}
    if workflows:
        workflow_ids = [w.id for w in workflows]
        default_count_query = select(Collection.default_workflow_id, func.count(Collection.id)).where(
            Collection.default_workflow_id.is_not(None)
        )
        if project_id is not None:
            default_count_query = default_count_query.where(Collection.project_id == project_id)
        elif scoped_project_ids:
            default_count_query = default_count_query.where(Collection.project_id.in_(scoped_project_ids))
        rows = (await db.execute(default_count_query.group_by(Collection.default_workflow_id))).all()
        default_counts = {str(workflow_id): count for workflow_id, count in rows}

        version_rows = (
            await db.execute(
                select(WorkflowVersion.workflow_id, func.max(WorkflowVersion.version_number))
                .where(WorkflowVersion.workflow_id.in_(workflow_ids))
                .group_by(WorkflowVersion.workflow_id)
            )
        ).all()
        latest_versions = {str(workflow_id): version_number for workflow_id, version_number in version_rows}

    items = [
        WorkflowListItem(
            **WorkflowResponse.model_validate(w).model_dump(),
            updated_at=w.updated_at,
            created_by_username=usernames.get(str(w.created_by)),
            is_system_default=w.project_id is None,
            default_for_collection_count=default_counts.get(str(w.id), 0),
            latest_version_number=latest_versions.get(str(w.id)),
            project_name=project_names.get(str(w.project_id)) if w.project_id is not None else None,
        )
        for w in workflows
    ]
    return {"items": items}


@router.get("/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow(
    workflow_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    workflow = await get_workflow_or_404(db, workflow_id)
    await check_workflow_access(db, workflow, current_user, min_role="viewer")
    return workflow


@router.patch("/{workflow_id}", response_model=WorkflowResponse)
async def update_workflow_status(
    workflow_id: UUID,
    data: WorkflowStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Row '⋮ 비활성화'와 이름 변경을 함께 처리한다. 상태 전환에 한해 다음 제약이 있다: 시스템 기본
    PREPROCESS 워크플로우는 비활성화할 수 없다 — 자체 워크플로우가 없는 모든
    프로젝트가 여기로 폴백하므로(_resolve_preprocess_version_id), 비활성화하면
    대체 워크플로우를 지정하는 기능이 없는 채로 업로드가 프로젝트 전역에서 깨진다."""
    workflow = await get_workflow_or_404(db, workflow_id)
    await check_workflow_access(db, workflow, current_user, min_role="editor")
    if data.status is not None:
        if data.status not in ("DRAFT", "ACTIVE", "INACTIVE"):
            raise HTTPException(status_code=400, detail="유효하지 않은 상태입니다")
        if workflow.project_id is None and data.status == "INACTIVE":
            raise HTTPException(
                status_code=409,
                detail="시스템 기본 워크플로우는 비활성화할 수 없습니다.",
            )
        workflow.status = data.status
    if data.name is not None:
        workflow.name = data.name.strip()
    await db.commit()
    await db.refresh(workflow)
    return workflow


@router.post("/{workflow_id}/duplicate", response_model=WorkflowResponse)
async def duplicate_workflow(
    workflow_id: UUID,
    data: WorkflowDuplicate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Row '⋮ 복제' action. Copies the source workflow's latest version's
    blocks/edges into a brand new workflow (always DRAFT, version 1) owned by
    the target project — including duplicating the system default (viewer
    access is enough on the source since nothing on it is modified)."""
    source = await get_workflow_or_404(db, workflow_id)
    await check_workflow_access(db, source, current_user, min_role="viewer")
    await check_project_access(db, data.project_id, current_user, min_role="editor")

    new_workflow = WorkflowDefinition(
        project_id=str(data.project_id),
        name=f"{source.name} 사본",
        description=source.description,
        kind=source.kind,
        created_by=str(current_user.id),
    )
    db.add(new_workflow)
    await db.flush()

    new_version = WorkflowVersion(workflow_id=new_workflow.id, version_number=1, created_by=str(current_user.id))
    db.add(new_version)
    await db.flush()

    latest_source_version = await db.scalar(
        select(WorkflowVersion)
        .where(WorkflowVersion.workflow_id == workflow_id)
        .order_by(WorkflowVersion.version_number.desc())
    )
    if latest_source_version is not None:
        await clone_graph(db, latest_source_version.id, new_version.id)

    await db.commit()
    await db.refresh(new_workflow)
    return new_workflow


@router.delete("/{workflow_id}")
async def delete_workflow(
    workflow_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Deletes the workflow and everything under it (versions, blocks, edges,
    runs, run steps). No FK cascades are defined on these tables, so children
    are removed explicitly in dependency order before the definition row."""
    workflow = await get_workflow_or_404(db, workflow_id)
    await check_workflow_access(db, workflow, current_user, min_role="editor")
    if workflow.project_id is None:
        raise HTTPException(
            status_code=409,
            detail="시스템 기본 워크플로우는 삭제할 수 없습니다.",
        )

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
