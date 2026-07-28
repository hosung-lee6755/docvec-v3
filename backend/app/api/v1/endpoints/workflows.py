from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import func

from app.api.v1.deps import get_current_user, require_admin
from app.api.v1.permissions import (
    accessible_project_ids,
    check_collection_access,
    check_document_access,
    check_project_access,
)
from app.db.models.collection import Collection
from app.db.models.document import Document
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
from app.services.workflow_service import validate_graph

router = APIRouter()


class WorkflowCreate(BaseModel):
    project_id: UUID
    name: str
    description: str | None = None
    kind: str = "ANALYSIS"

    @field_validator("kind")
    @classmethod
    def _validate_kind(cls, v: str) -> str:
        if v not in ("PREPROCESS", "ANALYSIS"):
            raise ValueError("kind must be one of PREPROCESS, ANALYSIS")
        return v


class WorkflowResponse(BaseModel):
    id: UUID
    project_id: UUID | None
    name: str
    description: str | None
    status: str
    kind: str
    created_at: datetime

    class Config:
        from_attributes = True


class WorkflowListItem(WorkflowResponse):
    updated_at: datetime
    # No separate updated_by column exists — created_by is the closest
    # attribution available and is shown as the list's "수정자" column.
    created_by_username: str | None
    # True for the single system-seeded PREPROCESS workflow every project falls
    # back to (project_id is None) — see _resolve_preprocess_version_id.
    is_system_default: bool
    # How many of this project's collections have their default_workflow_id
    # pinned to this workflow (documents.py's per-collection override, §2/§13).
    default_for_collection_count: int
    latest_version_number: int | None
    # Populated for the cross-project listing (project_id query param omitted)
    # so the UI can show a project badge per row; None for the system-default
    # workflow (project_id is None) and always populated for the single-project
    # listing too, for consistency.
    project_name: str | None = None


class WorkflowStatusUpdate(BaseModel):
    # 둘 다 선택값 — 이름만 바꾸는 요청과 상태만 바꾸는 기존 요청을 같은 엔드포인트로 받는다.
    status: str | None = None
    name: str | None = Field(None, min_length=1, max_length=200)


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


async def _check_workflow_access(
    db: AsyncSession, workflow: WorkflowDefinition, user: User, min_role: str,
) -> None:
    """Same project_id=None problem as _check_run_access, but for the
    workflow definition/version/graph endpoints themselves: the system-seeded
    standard PREPROCESS workflow has no project, so check_project_access
    would 404 with "Project not found" for every viewer, including the
    editor trying to open it. Any authenticated user may view it (it's the
    shared default every project can select); only a global admin may edit
    it, since a change affects every project's default processing."""
    if workflow.project_id is not None:
        await check_project_access(db, workflow.project_id, user, min_role=min_role)
        return
    if min_role == "viewer":
        return
    require_admin(user)


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
    workflow = await _get_workflow_or_404(db, workflow_id)
    await _check_workflow_access(db, workflow, current_user, min_role="viewer")
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
    workflow = await _get_workflow_or_404(db, workflow_id)
    await _check_workflow_access(db, workflow, current_user, min_role="editor")
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


class WorkflowDuplicate(BaseModel):
    project_id: UUID


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
    source = await _get_workflow_or_404(db, workflow_id)
    await _check_workflow_access(db, source, current_user, min_role="viewer")
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
        source_blocks = (
            await db.scalars(
                select(WorkflowBlockInstance).where(WorkflowBlockInstance.version_id == latest_source_version.id)
            )
        ).all()
        source_edges = (
            await db.scalars(select(WorkflowEdge).where(WorkflowEdge.version_id == latest_source_version.id))
        ).all()

        id_map: dict[str, str] = {}
        for block in source_blocks:
            new_block = WorkflowBlockInstance(
                version_id=new_version.id,
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
                version_id=new_version.id,
                from_block_id=id_map[str(edge.from_block_id)],
                to_block_id=id_map[str(edge.to_block_id)],
                condition=edge.condition,
            ))

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
    workflow = await _get_workflow_or_404(db, workflow_id)
    await _check_workflow_access(db, workflow, current_user, min_role="editor")
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


@router.get("/{workflow_id}/versions")
async def list_versions(
    workflow_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    workflow = await _get_workflow_or_404(db, workflow_id)
    await _check_workflow_access(db, workflow, current_user, min_role="viewer")
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
    await _check_workflow_access(db, workflow, current_user, min_role="editor")

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
    await _check_workflow_access(db, workflow, current_user, min_role="editor")
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
    await _check_workflow_access(db, workflow, current_user, min_role="viewer")
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
    await _check_workflow_access(db, workflow, current_user, min_role="editor")
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
    await _check_workflow_access(db, workflow, current_user, min_role="editor")
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
    await _check_workflow_access(db, workflow, current_user, min_role="editor")
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

    from app.pipeline.tasks.workflow import run_workflow_step, step_queue_for_block

    for run in runs:
        for block in entry_blocks:
            timeout_seconds = (block.config or {}).get("timeoutSeconds", 300)
            run_workflow_step.apply_async(
                args=[str(run.id), str(block.id)], time_limit=timeout_seconds,
                queue=step_queue_for_block(block),
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
    await _check_workflow_access(db, workflow, current_user, min_role="viewer")

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
