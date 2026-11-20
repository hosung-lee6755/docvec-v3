"""워크플로우를 쓸 수 있는 곳(2026-11-20 사용자 결정).

시스템 워크플로우(project_id 없음)는 어디서나 쓴다. 프로젝트 워크플로우는 같은 프로젝트의 컬렉션과 문서에만
쓴다. 개인 컬렉션(프로젝트 없음)은 시스템 워크플로우만 쓴다. 프로젝트 워크플로우에는 그 프로젝트의 임베딩
모델, 청크 방식, 민감정보 규칙, 분류 목록이 담기므로, 다른 프로젝트 문서에 쓰면 그 프로젝트의 설정이
섞인다.

검사하는 곳은 컬렉션 생성과 수정(collections.py), 업로드 때 고른 워크플로우(documents/upload.py),
워크플로우 화면의 직접 실행(workflows/runs.py), 재처리(reprocess_service.py)다.
"""
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


def fits_project(workflow_project_id, project_id) -> bool:
    """이 워크플로우를 이 프로젝트(None 이면 개인 컬렉션)에서 쓸 수 있는가."""
    if workflow_project_id is None:
        return True
    return project_id is not None and str(workflow_project_id) == str(project_id)


async def misfit_message(db: AsyncSession, workflow, project_id) -> str:
    from app.db.models.project import Project

    owner = await db.get(Project, workflow.project_id)
    owner_name = owner.name if owner is not None else "다른"
    target = "개인 컬렉션" if project_id is None else "다른 프로젝트의 컬렉션과 문서"
    return f"'{workflow.name}' 워크플로우는 '{owner_name}' 프로젝트 전용이라 {target}에는 쓸 수 없습니다"


async def ensure_fits_project(db: AsyncSession, workflow, project_id) -> None:
    if not fits_project(workflow.project_id, project_id):
        raise HTTPException(status_code=400, detail=await misfit_message(db, workflow, project_id))


async def collection_project_id(db: AsyncSession, collection_id):
    """컬렉션의 프로젝트. 컬렉션이 없거나 개인 컬렉션이면 None."""
    from app.db.models.collection import Collection

    if not collection_id:
        return None
    collection = await db.get(Collection, collection_id)
    return collection.project_id if collection is not None else None


async def default_preprocess_workflow_id(db: AsyncSession, collection):
    """컬렉션이 쓰는 전처리 워크플로우와 고정 버전. 컬렉션 지정이 없으면 시스템 표준 전처리다.
    업로드(_resolve_preprocess_version_id)와 재처리가 같은 기준을 쓴다."""
    from app.db.models.workflow import WorkflowDefinition

    if collection is not None and collection.default_workflow_id:
        return collection.default_workflow_id, collection.default_workflow_version
    system_workflow = await db.scalar(
        select(WorkflowDefinition).where(
            WorkflowDefinition.project_id.is_(None), WorkflowDefinition.kind == "PREPROCESS",
        )
    )
    return (system_workflow.id if system_workflow is not None else None), None
