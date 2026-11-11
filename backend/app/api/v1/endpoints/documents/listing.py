import asyncio
import logging
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import asc, cast, delete, desc, func, literal_column, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user
from app.api.v1.endpoints.documents.models import (
    BatchDeleteRequest,
    BatchReprocessItemResult,
    BatchReprocessRequest,
    BatchReprocessResponse,
)
from app.api.v1.permissions import (
    accessible_collection_ids,
    check_document_access,
    check_project_access,
)
from app.core.config import settings
from app.db.models.collection import Collection
from app.db.models.document import Document
from app.db.models.processing_job import ProcessingJob
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.document import (
    DocumentListResponse,
    DocumentResponse,
    DocumentSummarySearchRequest,
    DocumentSummarySearchResponse,
)
from app.services.access_policy import (
    build_access_context,
    document_visibility_clause,
    load_document_facts,
    qdrant_visibility_filter,
    visible_document_ids,
)
from app.services.audit import log_audit
from app.services.document_storage import release_original

router = APIRouter()

_SORT_COLUMNS = {
    "created_at": Document.created_at,
    "filename": Document.original_filename,
    "file_size": Document.file_size,
    "status": Document.status,
}


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=200),
    collection_id: UUID | None = None,
    project_id: UUID | None = None,
    status: str | None = None,
    filename: str | None = None,
    # v3 마일스톤 6: low_ocr(OCR 신뢰도 기준 미달 쪽이 있음), warning(경고나 일부 실패), failure(품질 실패)
    quality: Literal["low_ocr", "warning", "failure"] | None = None,
    sort_by: Literal["created_at", "filename", "file_size", "status"] = "created_at",
    order: Literal["asc", "desc"] = "desc",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    offset = (page - 1) * limit

    # v3 권한: 컬렉션 접근 + 보안등급 + 문서 ACL(+업로더 본인)을 한 SQL 조건으로 적용한다.
    ctx = await build_access_context(db, current_user)
    if project_id is not None:
        # Inside a project workspace, documents are scoped to the project's
        # collections regardless of who personally owns each document — unlike
        # the personal view below, ownership isn't the access boundary here.
        await check_project_access(db, project_id, current_user, min_role="viewer")
        project_collection_ids = await accessible_collection_ids(
            db, current_user, project_id=project_id
        )
        if not project_collection_ids:
            return {"total": 0, "page": page, "limit": limit, "items": []}
        filters = [
            Document.collection_id.in_(project_collection_ids),
            document_visibility_clause(ctx),
        ]
    else:
        filters = [document_visibility_clause(ctx)]
    if collection_id is not None:
        filters.append(Document.collection_id == collection_id)
    if status is not None:
        # 대시보드의 "처리중인 작업" 위젯이 11개 processing 상태를 한 번의
        # 쿼리로 가져오기 위해 콤마 구분 목록을 지원한다(2026-07-30) — 단일
        # 상태 호출은 split 결과가 1개짜리 리스트가 되어 동일하게 동작한다.
        statuses = [s for s in status.split(",") if s]
        filters.append(Document.status.in_(statuses))
    if filename:
        # Escape % and _ for SQL ILIKE to prevent wildcard injection
        escaped_filename = filename.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        filters.append(Document.original_filename.ilike(f"%{escaped_filename}%", escape="\\"))

    if quality is not None:
        filters.append(_quality_filter(quality))

    count_query = select(func.count(Document.id)).where(*filters)
    total = await db.scalar(count_query) or 0

    sort_column = _SORT_COLUMNS[sort_by]
    order_fn = asc if order == "asc" else desc
    result = await db.execute(
        select(Document)
        .where(*filters)
        .order_by(order_fn(sort_column))
        .offset(offset)
        .limit(limit)
    )
    documents = result.scalars().all()
    return {"total": total, "page": page, "limit": limit, "items": documents}


def _quality_filter(quality: str):
    if quality == "low_ocr":
        # asyncpg는 jsonpath 매개변수를 보내지 못하므로 SQL 리터럴로 쓴다. 비교값은 설정의 float이라
        # 사용자 입력이 들어가지 않는다
        threshold = float(settings.ocr_low_confidence)
        path = literal_column(f"'$[*] ? (@.confidence < {threshold})'::jsonpath")
        return cast(Document.ocr_page_confidence, JSONB).op("@?")(path)
    if quality == "warning":
        return Document.quality_status.in_(("SUCCESS_WITH_WARNING", "PARTIAL_FAILURE"))
    return Document.quality_status == "FAILURE"


# NOTE: must be declared before the /{document_id} routes below, or "tags"
# would be captured as a document_id path param and 422.
@router.get("/tags")
async def list_all_tags(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Distinct tags across every document the user can access — feeds the
    search page's tag-filter suggestion list."""
    ctx = await build_access_context(db, current_user)
    rows = await db.scalars(
        select(Document.tags).where(document_visibility_clause(ctx), Document.tags.isnot(None))
    )
    tags = sorted({tag for tag_list in rows for tag in (tag_list or [])})
    return {"tags": tags}


@router.post("/search/by-summary", response_model=DocumentSummarySearchResponse)
async def search_documents_by_summary(
    body: DocumentSummarySearchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """메타 정보 생성 설계서(2026-07-23) Phase 5 — Summary Index 검색.

    v3: 요약 포인트도 권한 사본(collection_id/sec_rank/acl/owner_id)을 싣으므로 Qdrant
    검색 단계에서 거른다 — 예전처럼 top-k를 자른 뒤 거르면 결과가 줄어든다. 그래도
    반환 직전에 Postgres 기준으로 다시 확인한다(페이로드 동기화 지연 대비, fail-closed).
    """
    from app.services.summary_index import search_document_summaries

    ctx = await build_access_context(db, current_user)
    # 목록과 같은 결과 집합 — 컬렉션 접근이 없어도 본인이 올린 문서는 검색된다.
    hits = await asyncio.to_thread(
        search_document_summaries, body.query, body.limit, qdrant_visibility_filter(ctx)
    )
    if not hits:
        return {"items": []}

    facts = await load_document_facts(db, {h["payload"].get("document_id") for h in hits})
    owned_or_shared_ids = visible_document_ids(ctx, facts)

    items = [
        {
            "document_id": h["payload"]["document_id"],
            "score": h["score"],
            "summary": h["payload"].get("summary", ""),
        }
        for h in hits
        if h["payload"].get("document_id") in owned_or_shared_ids
    ]
    return {"items": items}


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    doc = await db.scalar(select(Document).where(Document.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await check_document_access(db, doc, current_user, min_role="viewer")

    # 셀러리 hard time limit(TimeLimitExceeded)는 워커 fork 프로세스를 SIGKILL로
    # 죽여 애플리케이션 코드가 실패를 기록할 기회 자체가 없다. 별도 워커/beat 인프라
    # 없이, 프런트가 이미 처리중 상태를 3초 간격으로 폴링하는 이 조회 경로에서
    # 지연 감지해 멈춘 이유를 확정한다.
    from app.services.reprocess_service import reconcile_stuck_run

    await reconcile_stuck_run(db, doc)
    return doc


@router.delete("/batch")
async def batch_delete_documents(
    body: BatchDeleteRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.qdrant_service import qdrant_service
    from app.services.storage import storage_service
    from app.services.summary_index import delete_document_summary

    result = await db.execute(select(Document).where(Document.id.in_(body.ids)))
    candidates = result.scalars().all()
    owned_collection_ids = set(
        (await db.scalars(
            select(Collection.id).where(Collection.created_by == str(current_user.id))
        )).all()
    )
    # Defect 7: Fix UUID vs str comparison
    docs = [
        d for d in candidates
        if str(d.created_by) == str(current_user.id) or (d.collection_id and d.collection_id in owned_collection_ids)
    ]
    from sqlalchemy import update as sa_update

    from app.db.models.workflow_run import WorkflowRun

    doc_ids = [doc.id for doc in docs]
    if doc_ids:
        await db.execute(delete(ProcessingJob).where(ProcessingJob.document_id.in_(doc_ids)))
        # Keep workflow run history but drop the document link — the FK would
        # otherwise abort the delete (and previous attempts had already wiped
        # storage before hitting it, leaving zombie documents).
        await db.execute(
            sa_update(WorkflowRun)
            .where(WorkflowRun.document_id.in_(doc_ids))
            .values(document_id=None)
        )

    # Commit the DB delete FIRST: external cleanup below is best-effort and
    # must never resurrect rows by failing mid-way.
    cleanup = [(str(doc.id), doc.minio_key, list(doc.images or [])) for doc in docs]
    for doc in docs:
        # 감사 항목은 세션에 쌓였다가 아래 commit과 함께 저장된다(커밋 뒤에 호출하면 유실).
        log_audit(
            db, str(current_user.id), "document.delete", "document", str(doc.id),
            detail={"filename": doc.filename},
        )
        await db.delete(doc)
    await db.commit()

    for doc_id, minio_key, images in cleanup:
        # Defect E: Wrap blocking I/O in asyncio.to_thread
        # Defect B: Tolerate missing Qdrant collection
        try:
            await asyncio.to_thread(
                qdrant_service.delete_by_document, settings.qdrant_collection_name, doc_id
            )
        except Exception as exc:
            logging.warning(f"Failed to delete from Qdrant: {exc}")

        try:
            await asyncio.to_thread(delete_document_summary, doc_id)
        except Exception as exc:
            logging.warning(f"Failed to delete document summary: {exc}")

        await release_original(db, storage_service, settings.minio_bucket_originals, minio_key)

        for record in images:
            try:
                await asyncio.to_thread(
                    storage_service.delete_file, settings.minio_bucket_artifacts, record["storage_key"]
                )
            except Exception as exc:
                logging.warning(f"Failed to delete artifact: {exc}")
    return {"deleted": len(docs), "message": f"{len(docs)} documents deleted"}


@router.post("/batch-reprocess", response_model=BatchReprocessResponse)
async def batch_reprocess_documents(
    body: BatchReprocessRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """실패 목록에서 여러 문서를 선택해 한 번에 재처리한다. 문서마다 실제로
    실패한 블록 타입이 다를 수 있어(text_extract, classify, rag_store 등)
    /{document_id}/reprocess처럼 호출자가 start_block_type을 지정하게 하면
    선택한 문서 수만큼 사용자가 매번 알아내서 넣어야 한다 — 대신 각 문서의
    active_run_id에서 실제로 FAILED로 끝난 WorkflowRunStep을 찾아 그 블록부터
    자동으로 부분 재처리를 시작한다(2026-08-03, 실패 문서 일괄 재처리 시
    수동으로 했던 것과 동일한 방식)."""
    from app.db.models.workflow_run import WorkflowRun, WorkflowRunStep
    from app.services.reprocess_service import (
        ReprocessError,
        resolve_start_block,
        start_partial_reprocess,
    )

    results: list[BatchReprocessItemResult] = []
    for doc_id in body.ids:
        doc = await db.scalar(select(Document).where(Document.id == doc_id))
        if doc is None:
            results.append(BatchReprocessItemResult(id=doc_id, status="failed", detail="문서를 찾을 수 없습니다."))
            continue
        try:
            await check_document_access(db, doc, current_user, min_role="editor")
        except HTTPException as exc:
            results.append(BatchReprocessItemResult(id=doc_id, status="failed", detail=str(exc.detail)))
            continue

        if doc.status != "FAILED" or not doc.active_run_id:
            results.append(BatchReprocessItemResult(
                id=doc_id, status="skipped",
                detail=f"실패 상태의 문서만 재처리할 수 있습니다(현재 상태: {doc.status}).",
            ))
            continue

        parent_run = await db.get(WorkflowRun, doc.active_run_id)
        if parent_run is None:
            results.append(BatchReprocessItemResult(
                id=doc_id, status="failed", detail="원본 실행 기록을 찾을 수 없습니다.",
            ))
            continue

        failed_step = await db.scalar(
            select(WorkflowRunStep)
            .where(WorkflowRunStep.run_id == parent_run.id, WorkflowRunStep.status == "FAILED")
            .order_by(WorkflowRunStep.completed_at.desc())
        )
        if failed_step is None:
            results.append(BatchReprocessItemResult(
                id=doc_id, status="failed",
                detail="실패한 블록을 찾을 수 없어 자동으로 재처리를 시작할 수 없습니다. 문서 상세 페이지에서 직접 재처리해 주세요.",
            ))
            continue

        try:
            start_block = await resolve_start_block(
                db, parent_run.version_id, None, failed_step.block_instance_id,
            )
            new_run = await start_partial_reprocess(
                db, doc, start_block, reason="실패 목록 일괄 재처리",
            )
            results.append(BatchReprocessItemResult(id=doc_id, status="queued", run_id=new_run.id))
        except ReprocessError as exc:
            results.append(BatchReprocessItemResult(id=doc_id, status="failed", detail=str(exc)))

    return BatchReprocessResponse(results=results)


@router.delete("/{document_id}")
async def delete_document(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.qdrant_service import qdrant_service
    from app.services.storage import storage_service
    from app.services.summary_index import delete_document_summary

    doc = await db.scalar(select(Document).where(Document.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    is_owner = str(doc.created_by) == str(current_user.id)
    is_collection_owner = False
    if doc.collection_id:
        collection = await db.scalar(select(Collection).where(Collection.id == doc.collection_id))
        is_collection_owner = bool(collection) and str(collection.created_by) == str(current_user.id)
    if not (is_owner or is_collection_owner):
        raise HTTPException(status_code=403, detail="Access denied")

    from sqlalchemy import update as sa_update

    from app.db.models.workflow_run import WorkflowRun

    await db.execute(delete(ProcessingJob).where(ProcessingJob.document_id == document_id))
    # Keep workflow run history but drop the document link (FK would abort
    # the delete otherwise).
    await db.execute(
        sa_update(WorkflowRun)
        .where(WorkflowRun.document_id == document_id)
        .values(document_id=None)
    )
    log_audit(
        db, str(current_user.id), "document.delete", "document", str(doc.id),
        detail={"filename": doc.filename},
    )
    # Commit the DB delete FIRST — external cleanup is best-effort and must
    # never leave a half-deleted zombie row behind.
    minio_key, images = doc.minio_key, list(doc.images or [])
    await db.delete(doc)
    await db.commit()

    # Defect E: Wrap blocking I/O in asyncio.to_thread
    # Defect B: Tolerate missing Qdrant collection
    try:
        await asyncio.to_thread(
            qdrant_service.delete_by_document, settings.qdrant_collection_name, str(document_id)
        )
    except Exception as exc:
        logging.warning(f"Failed to delete from Qdrant: {exc}")

    try:
        await asyncio.to_thread(delete_document_summary, str(document_id))
    except Exception as exc:
        logging.warning(f"Failed to delete document summary: {exc}")

    await release_original(db, storage_service, settings.minio_bucket_originals, minio_key)

    for record in images:
        try:
            await asyncio.to_thread(
                storage_service.delete_file, settings.minio_bucket_artifacts, record["storage_key"]
            )
        except Exception as exc:
            logging.warning(f"Failed to delete artifact: {exc}")

    return {"message": "Document deleted"}



