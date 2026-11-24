"""문서를 다른 컬렉션으로 옮긴다 (2026-11-17 요청: 문서 컬렉션 이동).

컬렉션은 검색 범위와 권한(멤버, 기본 보안등급)을 정한다. 그래서 옮길 때는
- 옮기는 사람이 문서의 editor이면서 대상 컬렉션의 editor여야 하고,
- 보안등급을 상속하던 문서가 더 느슨한 등급의 컬렉션으로 가면 등급을 낮출 권한이 있어야 하며,
- 같은 계보(버전)의 문서를 함께 옮기고,
- Qdrant 포인트(본문 청크, 요약)의 collection_id와 권한 필드를 다시 맞춘다.
청크와 벡터는 그대로 둔다. 컬렉션마다 임베딩 모델이 다를 수 있으므로 모델이 다르면 옮기지 않는다.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user
from app.api.v1.endpoints.documents.models import BatchMoveItemResult, BatchMoveRequest, BatchMoveResponse
from app.api.v1.permissions import check_collection_access, check_document_access
from app.db.models.collection import Collection
from app.db.models.document import Document
from app.db.models.user import User
from app.db.session import get_db
from app.services.access_payload import sync_document_access
from app.services.access_policy import RELAX_FORBIDDEN_DETAIL, can_relax_document, is_relaxing_level
from app.services.audit import log_audit
from app.services.source_locks import ensure_not_connector_document

logger = logging.getLogger(__name__)
router = APIRouter()

# 처리 중인 문서는 워커가 문서의 컬렉션을 읽어 포인트에 쓰므로 옮기면 어긋난다.
# 검토 대기는 아직 임베딩 전이라 옮겨도 승인 뒤 새 컬렉션으로 색인된다.
MOVABLE_STATUSES = frozenset({"INDEXED", "FAILED", "CANCELLED", "WAITING_REVIEW"})
INDEX_SYNC_FAILED_DETAIL = "검색 색인에 반영하지 못해 옮기지 않았습니다. 잠시 뒤 다시 시도해 주세요."


async def _ensure_movable(db: AsyncSession, doc: Document, target: Collection, user: User) -> None:
    """옮길 수 없으면 HTTPException을 던진다. 아무것도 바꾸지 않는다."""
    await check_document_access(db, doc, user, min_role="editor")
    if str(doc.collection_id) == str(target.id):
        raise HTTPException(status_code=409, detail="이미 이 컬렉션에 있습니다.")
    if doc.status not in MOVABLE_STATUSES:
        raise HTTPException(status_code=409, detail=f"처리 중인 문서는 옮길 수 없습니다(현재 상태: {doc.status}).")
    await ensure_not_connector_document(db, doc.id)

    source = await db.get(Collection, doc.collection_id) if doc.collection_id else None
    if source is not None and source.embedding_model != target.embedding_model:
        raise HTTPException(
            status_code=409,
            detail="두 컬렉션의 임베딩 모델이 달라 옮길 수 없습니다. 대상 컬렉션에 다시 올려 주세요.",
        )
    duplicate = await db.scalar(
        select(Document.id).where(
            Document.collection_id == target.id,
            Document.file_hash == doc.file_hash,
            Document.lineage_id != doc.lineage_id,
        ).limit(1)
    )
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="대상 컬렉션에 같은 파일이 이미 있습니다.")

    old_level = doc.security_level or (source.default_security_level if source else None)
    new_level = doc.security_level or target.default_security_level
    if is_relaxing_level(old_level, new_level) and not await can_relax_document(db, user, doc):
        raise HTTPException(status_code=403, detail=RELAX_FORBIDDEN_DETAIL)


async def _lineage_locked(db: AsyncSession, doc: Document) -> list[Document]:
    """문서와 같은 계보의 모든 버전을 잠가서 가져온다. 옮기는 동안 재처리가 끼어들지 못하게 한다."""
    if doc.lineage_id is None:
        return [doc]
    versions = (
        await db.scalars(
            select(Document).where(Document.lineage_id == doc.lineage_id)
            .order_by(Document.version_number).with_for_update()
        )
    ).all()
    return list(versions) or [doc]


async def _drop_unfit_analysis_workflow(db: AsyncSession, doc: Document, target: Collection) -> None:
    """업로드 때 고른 프로젝트 전용 분석 워크플로우는 다른 프로젝트 컬렉션에서 쓸 수 없으므로 지운다. 그러면 옮긴 뒤의
    분석은 새 컬렉션의 기본 분석을 따른다(2026-11-24, services/workflow_scope.py 규칙)."""
    from app.db.models.workflow import WorkflowDefinition
    from app.services.workflow_scope import fits_project

    if not doc.analysis_workflow_id:
        return
    workflow = await db.get(WorkflowDefinition, doc.analysis_workflow_id)
    if workflow is None or not fits_project(workflow.project_id, target.project_id):
        doc.analysis_workflow_id = None


async def move_document(db: AsyncSession, doc: Document, target: Collection, user: User) -> list[str]:
    """문서와 같은 계보의 모든 버전을 대상 컬렉션으로 옮긴다(flush까지). 옮긴 문서 id 목록을 돌려준다.

    함께 옮기는 다른 버전도 권한, 상태, 중복, 등급 완화 검사를 똑같이 거친다. 하나라도 걸리면 아무것도 옮기지 않는다.
    """
    versions = await _lineage_locked(db, doc)
    for version in versions:
        try:
            await _ensure_movable(db, version, target, user)
        except HTTPException as exc:
            if version.id == doc.id:
                raise
            raise HTTPException(
                status_code=exc.status_code,
                detail=f"같은 문서의 다른 버전(v{version.version_number})을 옮길 수 없습니다. {exc.detail}",
            ) from exc
    from_collection = str(doc.collection_id) if doc.collection_id else None
    for version in versions:
        version.collection_id = target.id
        await _drop_unfit_analysis_workflow(db, version, target)
    log_audit(
        db, str(user.id), "document.move", "document", str(doc.id),
        detail={"from": from_collection, "to": str(target.id), "versions": len(versions)},
    )
    await db.flush()
    return [str(version.id) for version in versions]


async def _move_one(db: AsyncSession, doc_id, target: Collection, user: User) -> BatchMoveItemResult:
    """문서 하나를 세이브포인트 안에서 옮긴다. 실패하면 세이브포인트만 되돌려 다른 문서와 세션 객체는 그대로 둔다."""
    doc = await db.scalar(select(Document).where(Document.id == doc_id))
    if doc is None:
        return BatchMoveItemResult(id=doc_id, status="failed", detail="문서를 찾을 수 없습니다.")
    savepoint = await db.begin_nested()
    moved_ids: list[str] = []
    try:
        moved_ids = await move_document(db, doc, target, user)
        # 커밋 전에 Qdrant 포인트를 맞춘다(같은 세션이라 바뀐 컬렉션이 보인다)
        failed_sync = await sync_document_access(db, moved_ids)
        if failed_sync:
            raise RuntimeError(f"index sync failed for {failed_sync}")
        await savepoint.commit()
        await db.commit()
        return BatchMoveItemResult(id=doc_id, status="moved")
    except HTTPException as exc:
        await savepoint.rollback()
        status = "skipped" if exc.status_code == 409 else "failed"
        return BatchMoveItemResult(id=doc_id, status=status, detail=str(exc.detail))
    except Exception:
        logger.exception("document move failed document=%s", doc_id)
        if savepoint.is_active:
            await savepoint.rollback()
        await _restore_index(db, moved_ids)
        return BatchMoveItemResult(id=doc_id, status="failed", detail=INDEX_SYNC_FAILED_DETAIL)


async def _restore_index(db: AsyncSession, document_ids: list[str]) -> None:
    """옮기다 실패한 문서의 포인트를 Postgres(원래 컬렉션) 값으로 다시 맞춘다."""
    if not document_ids:
        return
    try:
        still_wrong = await sync_document_access(db, document_ids)
    except Exception:
        logger.exception("document move index restore failed documents=%s", document_ids)
        return
    if still_wrong:
        # 검색은 LLM에 넘기기 전에 Postgres로 다시 확인하므로 누출은 없다. 원래 컬렉션 검색에서만 빠진다
        logger.error("document move left stale index payload documents=%s", still_wrong)


@router.post("/batch-move", response_model=BatchMoveResponse)
async def batch_move_documents(
    body: BatchMoveRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """선택한 문서를 다른 컬렉션으로 옮긴다. 문서마다 결과(moved/skipped/failed)를 돌려준다.

    컬렉션 범위로 만든 예전 채팅 대화, 검색 기록, 답변 추적은 옮기지 않는다. 그 시점의 기록이기 때문이다.
    """
    target = await check_collection_access(db, body.collection_id, current_user, min_role="editor")
    results = [await _move_one(db, doc_id, target, current_user) for doc_id in body.ids]
    return BatchMoveResponse(results=results)
