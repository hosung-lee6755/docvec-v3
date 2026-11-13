"""워크플로우 엔드포인트 공통: 조회(404)와 접근 권한 검사."""
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import require_admin
from app.api.v1.permissions import (
    check_collection_access,
    check_document_access,
    check_project_access,
)
from app.db.models.document import Document
from app.db.models.user import User
from app.db.models.workflow import WorkflowDefinition, WorkflowVersion
from app.db.models.workflow_run import WorkflowRun


async def get_workflow_or_404(db: AsyncSession, workflow_id: UUID) -> WorkflowDefinition:
    workflow = await db.get(WorkflowDefinition, workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return workflow


async def get_version_or_404(db: AsyncSession, workflow_id: UUID, version_id: UUID) -> WorkflowVersion:
    version = await db.get(WorkflowVersion, version_id)
    if not version or str(version.workflow_id) != str(workflow_id):
        raise HTTPException(status_code=404, detail="Version not found")
    return version


async def check_run_access(
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
    # 대상 문서가 지워져 문서도 컬렉션도 남지 않은 실행. 처리 이력은 관리자만 보고, 다른 사용자에게는
    # 목록과 같이 없는 실행으로 보인다(403은 기록이 있다는 사실을 알려 준다).
    if user.role == "admin":
        return
    raise HTTPException(status_code=404, detail="Run not found")


async def check_workflow_access(
    db: AsyncSession, workflow: WorkflowDefinition, user: User, min_role: str,
) -> None:
    """Same project_id=None problem as check_run_access, but for the
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
