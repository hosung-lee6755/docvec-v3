import hashlib
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import asc, delete, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user, require_admin
from app.api.v1.permissions import (
    accessible_collection_ids,
    check_collection_access,
    check_document_access,
    check_project_access,
)
from app.core.config import settings
from app.db.models.collection import Collection
from app.db.models.document import Document
from app.db.models.processing_job import ProcessingJob
from app.db.models.user import User
from app.db.session import get_db
from app.db.models.document_revision import DocumentTextRevision
from app.services.audit import log_audit
from app.schemas.document import (
    ChunkUpdateRequest,
    CleaningChangesResponse,
    DictionaryApplicationItem,
    DictionaryApplicationsResponse,
    DocumentChunksResponse,
    DocumentContentResponse,
    DocumentDownloadResponse,
    DocumentImagesResponse,
    DocumentListResponse,
    DocumentNodeItem,
    DocumentNodesResponse,
    DocumentProceedRequest,
    DocumentReprocessRequest,
    DocumentResponse,
    DocumentRevisionsResponse,
    DocumentRunsResponse,
    DocumentTablesResponse,
    DocumentTagSuggestionRequest,
    DocumentTagsUpdateRequest,
    DocumentUploadResponse,
    NodeCorrectionRequest,
    PiiDetectionItem,
    PiiDetectionsResponse,
    QualityReportResponse,
    ReprocessImpactResponse,
)
from app.schemas.processing_job import ProcessingJobListResponse

router = APIRouter()


class BatchDeleteRequest(BaseModel):
    ids: list[UUID]


class BulkUploadItemResult(BaseModel):
    filename: str
    status: Literal["queued", "duplicate", "skipped", "failed"]
    document_id: UUID | None = None
    detail: str | None = None


class BulkUploadResponse(BaseModel):
    total_entries: int
    queued: int
    results: list[BulkUploadItemResult]


_SUPPORTED_UPLOAD_SUFFIXES = {".pdf", ".docx", ".hwp", ".hwpx"}
# Safety caps for a ZIP-bulk upload — this endpoint decompresses attacker-
# controllable archive content in memory, so both entry count and total
# uncompressed size need hard limits (classic zip-bomb surface).
_ZIP_MAX_ENTRIES = 200
_ZIP_MAX_ENTRY_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
_ZIP_MAX_TOTAL_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024


async def _resolve_preprocess_version_id(
    db: AsyncSession, collection_id: str | None, explicit_version_id: str | None = None,
):
    """업로드 다이얼로그에서 명시적으로 고른 workflow_version_id가 있으면 그것을
    최우선으로 쓰고(단, PREPROCESS 종류인지는 확인한다), 없으면
    Collection.default_workflow_id(+ default_workflow_version, null이면 항상
    최신 발행 버전) 순, 그마저도 없으면 시스템 표준 PREPROCESS 워크플로우의
    최신 발행 버전 — 통합 설계서 §13 Task 3 / §2 업로드 워크플로우 오버라이드."""
    from app.db.models.workflow import WorkflowDefinition, WorkflowVersion

    if explicit_version_id:
        version = await db.get(WorkflowVersion, explicit_version_id)
        if version is None:
            raise HTTPException(status_code=400, detail="지정한 워크플로우 버전을 찾을 수 없습니다")
        workflow = await db.get(WorkflowDefinition, version.workflow_id)
        if workflow is None or workflow.kind != "PREPROCESS":
            raise HTTPException(status_code=400, detail="전처리(PREPROCESS) 워크플로우 버전만 지정할 수 있습니다")
        return version.id

    workflow_id = None
    pinned_version_number = None
    if collection_id:
        collection = await db.get(Collection, collection_id)
        if collection is not None and collection.default_workflow_id:
            workflow_id = collection.default_workflow_id
            pinned_version_number = collection.default_workflow_version

    if workflow_id is None:
        system_workflow = await db.scalar(
            select(WorkflowDefinition).where(
                WorkflowDefinition.project_id.is_(None),
                WorkflowDefinition.kind == "PREPROCESS",
            )
        )
        if system_workflow is None:
            raise HTTPException(status_code=500, detail="표준 전처리 워크플로우가 설정되어 있지 않습니다")
        workflow_id = system_workflow.id

    version_query = select(WorkflowVersion).where(WorkflowVersion.workflow_id == workflow_id)
    if pinned_version_number is not None:
        version_query = version_query.where(WorkflowVersion.version_number == pinned_version_number)
    else:
        version_query = version_query.where(WorkflowVersion.published_at.is_not(None))
    version = await db.scalar(
        version_query.order_by(WorkflowVersion.version_number.desc()).limit(1)
    )
    if version is None:
        raise HTTPException(status_code=500, detail="게시된 전처리 워크플로우 버전이 없습니다")
    return version.id


async def _start_preprocess_workflow(
    db: AsyncSession, document: Document, workflow_version_id: str | None = None,
) -> None:
    """Replaces the retired fixed pipeline's create_processing_chain(...).delay()
    — creates a WorkflowRun against the resolved PREPROCESS version and
    enqueues its entry block(s), same pattern as workflows.py's /run endpoint."""
    from app.db.models.workflow import WorkflowBlockInstance, WorkflowEdge
    from app.db.models.workflow_run import WorkflowRun
    from app.pipeline.tasks.workflow import run_workflow_step, step_queue_for_block
    from app.services.dictionary_service import current_dictionary_version

    version_id = await _resolve_preprocess_version_id(
        db, str(document.collection_id) if document.collection_id else None, workflow_version_id,
    )
    dictionary_version = await current_dictionary_version(db)

    run = WorkflowRun(
        version_id=version_id, document_id=document.id, status="QUEUED", trigger="UPLOAD",
        dictionary_version=dictionary_version,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    document.active_run_id = run.id
    await db.commit()

    blocks = (
        await db.scalars(
            select(WorkflowBlockInstance).where(WorkflowBlockInstance.version_id == version_id)
        )
    ).all()
    edges = (
        await db.scalars(select(WorkflowEdge).where(WorkflowEdge.version_id == version_id))
    ).all()
    has_incoming = {e.to_block_id for e in edges}
    entry_blocks = [b for b in blocks if b.id not in has_incoming]

    for block in entry_blocks:
        timeout_seconds = (block.config or {}).get("timeoutSeconds", 300)
        run_workflow_step.apply_async(
            args=[str(run.id), str(block.id)], time_limit=timeout_seconds,
            queue=step_queue_for_block(block),
        )


@router.post("/upload", response_model=DocumentUploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    collection_id: str | None = Form(None),
    skip_review: bool = Form(False),
    workflow_version_id: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.storage import storage_service

    if collection_id is not None:
        await check_collection_access(db, collection_id, current_user, min_role="editor")

    content = await file.read()
    file_hash = hashlib.sha256(content).hexdigest()

    # Duplicate guard: the same bytes indexed twice in one collection produce
    # duplicate chunks that pollute retrieval. Delete the existing document
    # first if a re-index is intended.
    dup_filters = [Document.file_hash == file_hash]
    if collection_id is not None:
        dup_filters.append(Document.collection_id == collection_id)
    duplicate = await db.scalar(select(Document).where(*dup_filters).limit(1))
    if duplicate:
        raise HTTPException(
            status_code=409,
            detail=f"동일한 파일이 이미 존재합니다: {duplicate.original_filename}"
            f" (상태: {duplicate.status}). 다시 처리하려면 기존 문서를 먼저 삭제하세요.",
        )

    safe_name = file.filename or "upload"
    minio_key = f"{file_hash}/{safe_name}"

    storage_service.upload_file(
        settings.minio_bucket_originals,
        minio_key,
        content,
        file.content_type or "application/octet-stream",
    )

    document = Document(
        filename=safe_name,
        original_filename=safe_name,
        file_size=len(content),
        mime_type=file.content_type or "application/octet-stream",
        file_hash=file_hash,
        minio_key=minio_key,
        status="QUEUED",
        created_by=str(current_user.id),
        collection_id=collection_id,
    )
    db.add(document)
    await db.commit()
    await db.refresh(document)

    # skip_review: 표준 워크플로우(Phase 3)에는 아직 검토 게이트(quality_check,
    # Phase 7)가 없어 항상 즉시 진행과 동일하다 — 하위 호환을 위해 파라미터는
    # 받되 무시한다.
    await _start_preprocess_workflow(db, document, workflow_version_id)

    return {
        "id": document.id,
        "filename": document.filename,
        "status": document.status,
        "created_at": document.created_at,
    }


@router.post("/upload-zip", response_model=BulkUploadResponse)
async def upload_documents_zip(
    file: UploadFile = File(...),
    collection_id: str | None = Form(None),
    skip_review: bool = Form(False),
    workflow_version_id: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Extracts a .zip and registers each supported document inside it, one by
    one, so a batch that arrives pre-bundled (e.g. downloaded elsewhere) doesn't
    need to be unpacked by hand before uploading. Each entry gets the same
    duplicate check / storage / processing-chain kickoff as a single upload,
    but a bad entry only fails that entry — the response reports a per-file
    outcome instead of failing the whole request."""
    import io
    import mimetypes
    import zipfile
    from pathlib import PurePosixPath

    from app.services.storage import storage_service

    if collection_id is not None:
        await check_collection_access(db, collection_id, current_user, min_role="editor")

    zip_bytes = await file.read()
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="유효한 ZIP 파일이 아닙니다")

    entries = [
        info
        for info in zf.infolist()
        if not info.is_dir()
        and not info.filename.startswith("__MACOSX/")
        and not PurePosixPath(info.filename).name.startswith(".")
    ]
    if len(entries) > _ZIP_MAX_ENTRIES:
        raise HTTPException(
            status_code=400,
            detail=f"ZIP 안의 파일이 너무 많습니다 (최대 {_ZIP_MAX_ENTRIES}개, 현재 {len(entries)}개)",
        )
    if sum(info.file_size for info in entries) > _ZIP_MAX_TOTAL_UNCOMPRESSED_BYTES:
        raise HTTPException(status_code=400, detail="ZIP 압축 해제 시 총 용량이 너무 큽니다")

    results: list[dict] = []
    queued = 0
    for info in entries:
        # Flatten to the bare filename — zip entries may carry directory
        # components (including "../"-style traversal attempts), and none of
        # that path structure is meaningful once the file becomes a standalone
        # Document row keyed by content hash.
        entry_name = PurePosixPath(info.filename).name
        suffix = PurePosixPath(entry_name).suffix.lower()

        if suffix not in _SUPPORTED_UPLOAD_SUFFIXES:
            results.append({
                "filename": entry_name or info.filename,
                "status": "skipped",
                "detail": f"지원하지 않는 형식입니다: {suffix or '확장자 없음'}",
            })
            continue
        if info.file_size > _ZIP_MAX_ENTRY_UNCOMPRESSED_BYTES:
            results.append({
                "filename": entry_name,
                "status": "skipped",
                "detail": "파일이 너무 큽니다 (최대 200MB)",
            })
            continue

        try:
            content = zf.read(info)
        except Exception as exc:
            results.append({"filename": entry_name, "status": "failed", "detail": str(exc)[:200]})
            continue

        file_hash = hashlib.sha256(content).hexdigest()
        dup_filters = [Document.file_hash == file_hash]
        if collection_id is not None:
            dup_filters.append(Document.collection_id == collection_id)
        duplicate = await db.scalar(select(Document).where(*dup_filters).limit(1))
        if duplicate:
            results.append({
                "filename": entry_name,
                "status": "duplicate",
                "document_id": duplicate.id,
                "detail": f"동일한 파일이 이미 존재합니다: {duplicate.original_filename}",
            })
            continue

        try:
            minio_key = f"{file_hash}/{entry_name}"
            content_type = mimetypes.guess_type(entry_name)[0] or "application/octet-stream"
            storage_service.upload_file(
                settings.minio_bucket_originals, minio_key, content, content_type
            )

            document = Document(
                filename=entry_name,
                original_filename=entry_name,
                file_size=len(content),
                mime_type=content_type,
                file_hash=file_hash,
                minio_key=minio_key,
                status="QUEUED",
                created_by=str(current_user.id),
                collection_id=collection_id,
            )
            db.add(document)
            await db.commit()
            await db.refresh(document)

            # skip_review: 이번 단계 표준 워크플로우엔 검토 게이트가 없어
            # 무시됨(단일 업로드와 동일 — 위 주석 참고).
            await _start_preprocess_workflow(db, document, workflow_version_id)
            results.append({"filename": entry_name, "status": "queued", "document_id": document.id})
            queued += 1
        except Exception as exc:
            await db.rollback()
            results.append({"filename": entry_name, "status": "failed", "detail": str(exc)[:200]})

    return {"total_entries": len(entries), "queued": queued, "results": results}


_SORT_COLUMNS = {
    "created_at": Document.created_at,
    "filename": Document.original_filename,
    "file_size": Document.file_size,
    "status": Document.status,
}


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    page: int = 1,
    limit: int = 10,
    collection_id: UUID | None = None,
    project_id: UUID | None = None,
    status: str | None = None,
    filename: str | None = None,
    sort_by: Literal["created_at", "filename", "file_size", "status"] = "created_at",
    order: Literal["asc", "desc"] = "desc",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    offset = (page - 1) * limit

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
        filters = [Document.collection_id.in_(project_collection_ids)]
    else:
        shared_ids = await accessible_collection_ids(db, current_user)
        owned_or_shared = [Document.created_by == str(current_user.id)]
        if shared_ids:
            owned_or_shared.append(Document.collection_id.in_(shared_ids))
        filters = [or_(*owned_or_shared)]
    if collection_id is not None:
        filters.append(Document.collection_id == collection_id)
    if status is not None:
        filters.append(Document.status == status)
    if filename:
        filters.append(Document.original_filename.ilike(f"%{filename}%"))

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


# NOTE: must be declared before the /{document_id} routes below, or "tags"
# would be captured as a document_id path param and 422.
@router.get("/tags")
async def list_all_tags(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Distinct tags across every document the user can access — feeds the
    search page's tag-filter suggestion list."""
    shared_ids = await accessible_collection_ids(db, current_user)
    owned_or_shared = [Document.created_by == str(current_user.id)]
    if shared_ids:
        owned_or_shared.append(Document.collection_id.in_(shared_ids))

    rows = await db.scalars(
        select(Document.tags).where(or_(*owned_or_shared), Document.tags.isnot(None))
    )
    tags = sorted({tag for tag_list in rows for tag in (tag_list or [])})
    return {"tags": tags}


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
    return doc


@router.delete("/batch")
async def batch_delete_documents(
    body: BatchDeleteRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.qdrant_service import qdrant_service
    from app.services.storage import storage_service

    result = await db.execute(select(Document).where(Document.id.in_(body.ids)))
    candidates = result.scalars().all()
    owned_collection_ids = set(
        (await db.scalars(
            select(Collection.id).where(Collection.created_by == str(current_user.id))
        )).all()
    )
    docs = [
        d for d in candidates
        if str(d.created_by) == str(current_user.id) or d.collection_id in owned_collection_ids
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
        await db.delete(doc)
    await db.commit()

    for doc_id, minio_key, images in cleanup:
        qdrant_service.delete_by_document(settings.qdrant_collection_name, doc_id)
        storage_service.delete_file(settings.minio_bucket_originals, minio_key)
        for record in images:
            storage_service.delete_file(settings.minio_bucket_artifacts, record["storage_key"])
    return {"deleted": len(docs), "message": f"{len(docs)} documents deleted"}


@router.delete("/{document_id}")
async def delete_document(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.qdrant_service import qdrant_service
    from app.services.storage import storage_service

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

    qdrant_service.delete_by_document(settings.qdrant_collection_name, str(document_id))
    storage_service.delete_file(settings.minio_bucket_originals, minio_key)
    for record in images:
        storage_service.delete_file(settings.minio_bucket_artifacts, record["storage_key"])
    return {"message": "Document deleted"}


@router.get("/{document_id}/status")
async def get_document_status(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    doc = await db.scalar(select(Document).where(Document.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await check_document_access(db, doc, current_user, min_role="viewer")
    return {"status": doc.status, "error_message": doc.error_message}


@router.post("/{document_id}/proceed")
async def proceed_document(
    document_id: UUID,
    body: DocumentProceedRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.pipeline.tasks.process import continue_processing

    doc = await db.scalar(select(Document).where(Document.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await check_document_access(db, doc, current_user, min_role="editor")
    if doc.status != "REVIEW_PENDING":
        raise HTTPException(
            status_code=409,
            detail=f"Document is not awaiting review (status={doc.status})",
        )

    if body.edited_text is not None:
        doc.parsed_text = body.edited_text
        db.add(
            DocumentTextRevision(
                document_id=document_id,
                source="REVIEW_EDIT",
                parsed_text=body.edited_text,
                created_by=str(current_user.id),
            )
        )
        await db.commit()

    continue_processing.delay(str(document_id))
    return {"message": "Processing resumed", "status": "CHUNKING"}


@router.post("/{document_id}/reprocess")
async def reprocess_document(
    document_id: UUID,
    body: DocumentReprocessRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    doc = await db.scalar(select(Document).where(Document.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await check_document_access(db, doc, current_user, min_role="editor")
    if doc.status != "INDEXED":
        raise HTTPException(
            status_code=409,
            detail=f"Document is not indexed yet (status={doc.status})",
        )

    if body.start_block_type is not None or body.start_block_instance_id is not None:
        from app.db.models.workflow_run import WorkflowRun as _WorkflowRun
        from app.services.reprocess_service import (
            ReprocessError,
            resolve_start_block,
            start_partial_reprocess,
        )

        parent_run = await db.get(_WorkflowRun, doc.active_run_id) if doc.active_run_id else None
        if parent_run is None:
            raise HTTPException(
                status_code=409,
                detail="이 문서는 아직 워크플로우로 처리된 적이 없어 이 기능을 사용할 수 없습니다.",
            )

        try:
            start_block = await resolve_start_block(
                db, parent_run.version_id, body.start_block_type, body.start_block_instance_id,
            )
            new_run = await start_partial_reprocess(db, doc, start_block, body.reason)
        except ReprocessError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        return {
            "message": "부분 재처리가 시작되었습니다",
            "run_id": str(new_run.id),
            "status": "QUEUED",
            "impact": new_run.impact,
        }

    from app.pipeline.tasks.process import continue_processing

    db.add(
        DocumentTextRevision(
            document_id=document_id,
            source="RAG_EDIT",
            parsed_text=body.edited_text,
            created_by=str(current_user.id),
        )
    )
    await db.commit()

    continue_processing.delay(str(document_id), edited_text=body.edited_text)
    return {"message": "Reprocessing started", "status": "CHUNKING"}


@router.get("/{document_id}/runs", response_model=DocumentRunsResponse)
async def list_document_runs(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.db.models.workflow_run import WorkflowRun

    doc = await db.scalar(select(Document).where(Document.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await check_document_access(db, doc, current_user, min_role="viewer")

    runs = (
        await db.scalars(
            select(WorkflowRun)
            .where(WorkflowRun.document_id == document_id)
            .order_by(desc(WorkflowRun.created_at))
        )
    ).all()
    return {"document_id": str(document_id), "runs": runs}


@router.get("/{document_id}/quality", response_model=QualityReportResponse | None)
async def get_document_quality(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.db.models.quality_report import QualityReport

    doc = await db.scalar(select(Document).where(Document.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await check_document_access(db, doc, current_user, min_role="viewer")

    report = None
    if doc.active_run_id:
        report = await db.scalar(
            select(QualityReport).where(QualityReport.run_id == doc.active_run_id)
        )
    if report is None:
        # 구버전 문서 마이그레이션(설계서 §14)이나 active_run_id가 비어 있는 경우 —
        # 이 문서에 대해 가장 최근에 계산된 리포트라도 보여준다.
        report = await db.scalar(
            select(QualityReport)
            .where(QualityReport.document_id == document_id)
            .order_by(desc(QualityReport.created_at))
            .limit(1)
        )
    return report


@router.get("/{document_id}/reprocess/impact", response_model=ReprocessImpactResponse)
async def get_document_reprocess_impact(
    document_id: UUID,
    start_block_type: str | None = None,
    start_block_instance_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """부분 재처리 시작 전 영향 범위 미리보기 — WorkflowRun을 생성하지 않는다
    (재처리 모달, 통합 설계서 §9.1 처리 이력 탭/§7 재처리 모달)."""
    from app.db.models.workflow_run import WorkflowRun as _WorkflowRun
    from app.services.reprocess_service import ReprocessError, compute_reprocess_impact, resolve_start_block

    if start_block_type is None and start_block_instance_id is None:
        raise HTTPException(
            status_code=422, detail="start_block_type 또는 start_block_instance_id 중 하나가 필요합니다.",
        )

    doc = await db.scalar(select(Document).where(Document.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await check_document_access(db, doc, current_user, min_role="viewer")

    parent_run = await db.get(_WorkflowRun, doc.active_run_id) if doc.active_run_id else None
    if parent_run is None:
        raise HTTPException(
            status_code=409,
            detail="이 문서는 아직 워크플로우로 처리된 적이 없어 이 기능을 사용할 수 없습니다.",
        )

    try:
        start_block = await resolve_start_block(
            db, parent_run.version_id, start_block_type, start_block_instance_id,
        )
        computed = await compute_reprocess_impact(db, doc, start_block)
    except ReprocessError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return computed.impact


async def _resolve_display_run_id(db: AsyncSession, doc: Document) -> str | None:
    """활성 run 우선, 없으면 최신 run — get_document_quality가 쓰는 폴백과 동일 기준으로
    구조/정제/사전적용/PII 탭이 "어느 run의 데이터를 보여줄지"를 통일한다. 각 테이블이
    run_id로 여러 실행 결과를 구분해 쌓기 때문에(재처리마다 새 결과가 추가됨) 하나로
    고정하지 않으면 여러 run의 데이터가 뒤섞여 보인다."""
    if doc.active_run_id:
        return str(doc.active_run_id)
    from app.db.models.workflow_run import WorkflowRun as _WorkflowRun

    run_id = await db.scalar(
        select(_WorkflowRun.id)
        .where(_WorkflowRun.document_id == doc.id)
        .order_by(desc(_WorkflowRun.created_at))
        .limit(1)
    )
    return str(run_id) if run_id else None


@router.get("/{document_id}/nodes", response_model=DocumentNodesResponse)
async def list_document_nodes(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.db.models.document_node import DocumentNode

    doc = await db.scalar(select(Document).where(Document.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await check_document_access(db, doc, current_user, min_role="viewer")

    run_id = await _resolve_display_run_id(db, doc)
    nodes = []
    if run_id:
        nodes = (
            await db.scalars(
                select(DocumentNode)
                .where(DocumentNode.run_id == run_id)
                .order_by(DocumentNode.sort_order.asc())
            )
        ).all()
    return {"document_id": str(document_id), "run_id": run_id, "nodes": nodes}


@router.patch("/{document_id}/nodes/{node_id}", response_model=DocumentNodeItem)
async def correct_document_node(
    document_id: UUID,
    node_id: UUID,
    body: NodeCorrectionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.db.models.document_node import DocumentNode

    doc = await db.scalar(select(Document).where(Document.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await check_document_access(db, doc, current_user, min_role="editor")

    node = await db.scalar(
        select(DocumentNode).where(DocumentNode.id == node_id, DocumentNode.document_id == document_id)
    )
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    if body.node_type is not None:
        allowed_types = DocumentNode.__table__.c.node_type.type.enums
        if body.node_type not in allowed_types:
            raise HTTPException(status_code=422, detail=f"허용되지 않는 node_type: {body.node_type}")
        node.node_type = body.node_type
    if body.level is not None:
        node.level = body.level
    node.user_corrected = True
    await db.commit()
    await db.refresh(node)
    return node


@router.get("/{document_id}/cleaning-changes", response_model=CleaningChangesResponse)
async def list_cleaning_changes(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.db.models.cleaning_rule import CleaningChange, CleaningRule

    doc = await db.scalar(select(Document).where(Document.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await check_document_access(db, doc, current_user, min_role="viewer")

    run_id = await _resolve_display_run_id(db, doc)
    items: list[dict] = []
    if run_id:
        rows = (
            await db.execute(
                select(CleaningChange, CleaningRule.rule_name)
                .outerjoin(CleaningRule, CleaningChange.rule_id == CleaningRule.id)
                .where(CleaningChange.run_id == run_id)
                .order_by(CleaningChange.created_at.asc())
            )
        ).all()
        for change, rule_name in rows:
            items.append({
                "id": change.id,
                "rule_id": change.rule_id,
                "rule_key": change.rule_key,
                "rule_name": rule_name,
                "node_id": change.node_id,
                "before_sample": change.before_sample,
                "after_sample": change.after_sample,
                "change_count": change.change_count,
                "sample_matches": change.sample_matches,
                "created_at": change.created_at,
            })

    distinct_rules = {(item["rule_id"], item["rule_key"]) for item in items}
    return {
        "document_id": str(document_id),
        "run_id": run_id,
        "total_changes": sum(item["change_count"] for item in items),
        "distinct_rule_count": len(distinct_rules),
        "changes": items,
    }


@router.get("/{document_id}/dictionary-applications", response_model=DictionaryApplicationsResponse)
async def list_dictionary_applications(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.db.models.dictionary_application import DictionaryApplication

    doc = await db.scalar(select(Document).where(Document.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await check_document_access(db, doc, current_user, min_role="viewer")

    run_id = await _resolve_display_run_id(db, doc)
    applications = []
    if run_id:
        applications = (
            await db.scalars(
                select(DictionaryApplication)
                .where(DictionaryApplication.run_id == run_id)
                .order_by(DictionaryApplication.created_at.asc())
            )
        ).all()
    pending_revert_count = sum(1 for app_row in applications if app_row.reverted)
    return {
        "document_id": str(document_id),
        "run_id": run_id,
        "pending_revert_count": pending_revert_count,
        "applications": applications,
    }


@router.post(
    "/{document_id}/dictionary-applications/{app_id}/revert",
    response_model=DictionaryApplicationItem,
)
async def revert_dictionary_application(
    document_id: UUID,
    app_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.db.models.dictionary_application import DictionaryApplication

    doc = await db.scalar(select(Document).where(Document.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await check_document_access(db, doc, current_user, min_role="editor")

    application = await db.scalar(
        select(DictionaryApplication).where(
            DictionaryApplication.id == app_id,
            DictionaryApplication.document_id == document_id,
        )
    )
    if not application:
        raise HTTPException(status_code=404, detail="Dictionary application not found")

    application.reverted = True
    await db.commit()
    await db.refresh(application)
    return application


@router.get("/{document_id}/pii", response_model=PiiDetectionsResponse)
async def list_pii_detections(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.db.models.pii_detection import PiiDetection

    doc = await db.scalar(select(Document).where(Document.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await check_document_access(db, doc, current_user, min_role="viewer")

    run_id = await _resolve_display_run_id(db, doc)
    detections = []
    if run_id:
        detections = (
            await db.scalars(
                select(PiiDetection)
                .where(PiiDetection.run_id == run_id)
                .order_by(PiiDetection.created_at.asc())
            )
        ).all()
    return {"document_id": str(document_id), "run_id": run_id, "detections": detections}


@router.post("/{document_id}/pii/{detection_id}/approve", response_model=PiiDetectionItem)
async def approve_pii_detection(
    document_id: UUID,
    detection_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from datetime import datetime

    from app.db.models.pii_detection import PiiDetection

    doc = await db.scalar(select(Document).where(Document.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await check_document_access(db, doc, current_user, min_role="editor")

    detection = await db.scalar(
        select(PiiDetection).where(
            PiiDetection.id == detection_id, PiiDetection.document_id == document_id
        )
    )
    if not detection:
        raise HTTPException(status_code=404, detail="PII detection not found")

    detection.approved_by = current_user.id
    detection.approved_at = datetime.utcnow()
    detection.rejected = False
    await db.commit()
    await db.refresh(detection)
    return detection


@router.post("/{document_id}/pii/{detection_id}/reject", response_model=PiiDetectionItem)
async def reject_pii_detection(
    document_id: UUID,
    detection_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.db.models.pii_detection import PiiDetection

    doc = await db.scalar(select(Document).where(Document.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await check_document_access(db, doc, current_user, min_role="editor")

    detection = await db.scalar(
        select(PiiDetection).where(
            PiiDetection.id == detection_id, PiiDetection.document_id == document_id
        )
    )
    if not detection:
        raise HTTPException(status_code=404, detail="PII detection not found")

    detection.rejected = True
    detection.approved_by = None
    detection.approved_at = None
    await db.commit()
    await db.refresh(detection)
    return detection


class PiiRevealResponse(BaseModel):
    value: str


@router.post("/{document_id}/pii/{detection_id}/reveal", response_model=PiiRevealResponse)
async def reveal_pii_detection(
    document_id: UUID,
    detection_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """민감정보 원문 열람 — 문서별 editor 권한이 아니라 전역 admin 롤로 게이팅한다
    (9c에서 만든 목록/승인/반려 엔드포인트는 그대로 두고, 원문 노출만 별도 엔드포인트로
    분리해 PiiDetectionsResponse가 여전히 original_encrypted를 절대 반환하지 않는다는
    보안 보장을 유지한다). 모든 열람은 감사 로그에 남긴다."""
    from app.core import crypto
    from app.db.models.pii_detection import PiiDetection

    require_admin(current_user)

    doc = await db.scalar(select(Document).where(Document.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    detection = await db.scalar(
        select(PiiDetection).where(
            PiiDetection.id == detection_id, PiiDetection.document_id == document_id
        )
    )
    if not detection:
        raise HTTPException(status_code=404, detail="PII detection not found")
    if not detection.original_encrypted:
        raise HTTPException(status_code=404, detail="원문이 저장되어 있지 않습니다")

    value = crypto.decrypt_secret(detection.original_encrypted)
    log_audit(
        db, str(current_user.id), "pii.reveal",
        resource_type="pii_detection", resource_id=str(detection_id),
    )
    await db.commit()
    return {"value": value}


@router.get("/{document_id}/jobs", response_model=ProcessingJobListResponse)
async def get_document_jobs(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    doc = await db.scalar(select(Document).where(Document.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await check_document_access(db, doc, current_user, min_role="viewer")

    result = await db.execute(
        select(ProcessingJob)
        .where(ProcessingJob.document_id == document_id)
        .order_by(ProcessingJob.created_at.asc())
    )
    jobs = result.scalars().all()
    return {"items": jobs}


@router.get("/{document_id}/content", response_model=DocumentContentResponse)
async def get_document_content(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.document_service import get_document_content as fetch_content

    doc = await db.scalar(select(Document).where(Document.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await check_document_access(db, doc, current_user, min_role="viewer")
    return fetch_content(document_id)


@router.get("/{document_id}/tables", response_model=DocumentTablesResponse)
async def get_document_tables(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    doc = await db.scalar(select(Document).where(Document.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await check_document_access(db, doc, current_user, min_role="viewer")
    return {"document_id": str(doc.id), "tables": doc.tables or []}


@router.get("/{document_id}/chunks", response_model=DocumentChunksResponse)
async def list_document_chunks(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    import asyncio

    from app.services.chunk_stats import get_hit_counts
    from app.services.qdrant_service import qdrant_service

    doc = await db.scalar(select(Document).where(Document.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await check_document_access(db, doc, current_user, min_role="viewer")

    # structure/cleaning-changes/dictionary-applications/pii/quality 탭과 동일한
    # run 해석 기준(_resolve_display_run_id) — active_run_id 우선, 없으면 최신 run.
    run_id = await _resolve_display_run_id(db, doc)

    hits = qdrant_service.scroll_by_document(str(document_id))
    # 이 문서의 "현재" run이 아닌 다른(초과/삭제된) run이 남긴 포인트는 무시한다 —
    # reprocess로 새 run이 만들어져도 rag_store가 재실행되기 전까지는 Qdrant에
    # 이전 run의 임베딩이 그대로 남아 있고, 심지어 그 run 행 자체가 나중에
    # 삭제돼도(workflow_runs FK CASCADE는 Postgres document_chunks만 지우고
    # Qdrant는 건드리지 않음) 포인트는 고아 상태로 계속 남는다. 이걸 그대로
    # 보여주면 RAG 현황/품질 탭의 청크 수가 서로 달라 보이는 버그가 된다(사용자
    # 확인 2026-07-21, "01 포항세라믹... RAG 현황의 청크 수치랑 품질의 청크
    # 수치가 다르다" — 실제로 존재하지도 않는 run_id d5de7cc8...의 고아 포인트
    # 16개가 현재 run의 실제 청크 25개 대신 보이고 있었다).
    hits = [h for h in hits if h["payload"].get("workflow_run_id") == run_id]
    hits.sort(key=lambda h: h["payload"].get("chunk_index", 0))

    if not hits:
        # rag_store(임베딩+Qdrant 적재)는 quality_check 등 검토 게이트보다
        # 하류라서, WAITING_REVIEW로 멈춘 문서는 chunk_split이 이미 만든
        # document_chunks(Postgres) 행은 있어도 Qdrant는 아직 비어 있다 —
        # 그래서 이전에는 이 상태의 문서가 항상 "청크 0개"로 보였다(사용자 확인
        # 2026-07-21, "청크가 0으로 나온다... 품질에서는 생성된 청크 37개").
        # DocumentChunk 모델 자체의 설계 의도("Qdrant 없이도 청크 탭이 목록을
        # 볼 수 있도록")대로 Postgres를 폴백 소스로 사용한다 — 단, 이 경로로
        # 나온 항목은 embedded=False로 표시해 프런트가 수정/삭제(Qdrant 전용
        # 엔드포인트)를 비활성화하도록 한다.
        from app.db.models.document_chunk import DocumentChunk

        pg_chunks = (
            await db.scalars(
                select(DocumentChunk)
                .where(DocumentChunk.document_id == document_id, DocumentChunk.run_id == run_id)
                .order_by(DocumentChunk.chunk_order)
            )
        ).all() if run_id else []
        chunks = [
            {
                "id": str(c.id),
                "chunk_index": c.chunk_order,
                "text": c.chunk_text,
                "page_number": c.page_start,
                "disabled": False,
                "edited": c.edited,
                "hit_count": 0,
                "embedded": False,
            }
            for c in pg_chunks
        ]
        return {"document_id": str(document_id), "chunks": chunks}

    hit_counts = await asyncio.to_thread(get_hit_counts, [h["id"] for h in hits])
    chunks = [
        {
            "id": h["id"],
            "chunk_index": h["payload"].get("chunk_index", i),
            "text": h["payload"].get("text", ""),
            "page_number": h["payload"].get("page_number"),
            "disabled": bool(h["payload"].get("disabled", False)),
            "edited": bool(h["payload"].get("edited", False)),
            "hit_count": hit_counts.get(h["id"], 0),
            "embedded": True,
        }
        for i, h in enumerate(hits)
    ]
    return {"document_id": str(document_id), "chunks": chunks}


@router.patch("/{document_id}/chunks/{chunk_id}")
async def update_document_chunk(
    document_id: UUID,
    chunk_id: str,
    body: ChunkUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    import asyncio

    from app.services.qdrant_service import qdrant_service

    doc = await db.scalar(select(Document).where(Document.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await check_document_access(db, doc, current_user, min_role="editor")

    point = qdrant_service.get_point(settings.qdrant_collection_name, chunk_id)
    if point is None or point["payload"].get("document_id") != str(document_id):
        raise HTTPException(status_code=404, detail="Chunk not found")

    if body.disabled is not None:
        qdrant_service.set_point_payload(
            settings.qdrant_collection_name, chunk_id, {"disabled": body.disabled}
        )

    if body.text is not None:
        from app.pipeline.tasks.chunks import update_chunk_text

        # Re-embedding must run on the worker (resident model). Block this
        # request thread — not the event loop — until it lands so the UI can
        # refetch immediately after a 200.
        result = update_chunk_text.delay(str(document_id), chunk_id, body.text)
        try:
            outcome = await asyncio.to_thread(result.get, timeout=60)
        except Exception as exc:
            raise HTTPException(status_code=504, detail=f"청크 재임베딩 실패: {exc}") from exc
        if outcome.get("status") != "OK":
            raise HTTPException(status_code=404, detail="Chunk not found")

    return {"message": "Chunk updated"}


@router.delete("/{document_id}/chunks/{chunk_id}")
async def delete_document_chunk(
    document_id: UUID,
    chunk_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.db.models.document_chunk import DocumentChunk
    from app.db.models.quality_report import QualityReport
    from app.services.qdrant_service import qdrant_service

    doc = await db.scalar(select(Document).where(Document.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await check_document_access(db, doc, current_user, min_role="editor")

    point = qdrant_service.get_point(settings.qdrant_collection_name, chunk_id)
    if point is None or point["payload"].get("document_id") != str(document_id):
        raise HTTPException(status_code=404, detail="Chunk not found")

    qdrant_service.delete_points(settings.qdrant_collection_name, [chunk_id])

    # document_chunks is the first-class source of truth (§4.6) — deleting only
    # the Qdrant point left this row behind forever, stale and still counted
    # by anything that queries document_chunks directly (사용자 확인 2026-07-21,
    # "청크를 삭제한다면 RAG에서도 지워지는 구조가 맞는지도 검토해달라").
    await db.execute(delete(DocumentChunk).where(DocumentChunk.id == chunk_id))

    # If this chunk was the one a chunking warning pointed at, drop it from the
    # report so a resolved issue stops showing as still needing review
    # (사용자 확인 2026-07-21, "문제의 청크를 삭제했는데 계속 검토 필요로 남아있다").
    report = None
    if doc.active_run_id:
        report = await db.scalar(select(QualityReport).where(QualityReport.run_id == doc.active_run_id))
    if report is None:
        report = await db.scalar(
            select(QualityReport).where(QualityReport.document_id == document_id)
            .order_by(desc(QualityReport.created_at)).limit(1)
        )
    if report is not None and report.metrics:
        changed = False
        metrics = dict(report.metrics)
        warnings = list(report.warnings or [])
        categories = list(report.warning_categories or [])
        for key, category in (("short_chunk_ids", "chunking_short"), ("long_chunk_ids", "chunking_long")):
            ids = metrics.get(key) or []
            if chunk_id not in ids:
                continue
            ids = [i for i in ids if i != chunk_id]
            metrics[key] = ids
            changed = True
            if not ids and category in categories:
                idx = categories.index(category)
                warnings.pop(idx)
                categories.pop(idx)
        if changed:
            report.metrics = metrics
            report.warnings = warnings
            report.warning_categories = categories

    await db.commit()
    return {"message": "Chunk deleted"}


_REVISION_PREVIEW_CHARS = 120


@router.get("/{document_id}/revisions", response_model=DocumentRevisionsResponse)
async def list_document_revisions(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    doc = await db.scalar(select(Document).where(Document.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await check_document_access(db, doc, current_user, min_role="viewer")

    result = await db.execute(
        select(DocumentTextRevision)
        .where(DocumentTextRevision.document_id == document_id)
        .order_by(DocumentTextRevision.created_at.desc())
        .limit(50)
    )
    revisions = [
        {
            "id": r.id,
            "source": r.source,
            "created_by": r.created_by,
            "created_at": r.created_at,
            "text_length": len(r.parsed_text),
            "preview": r.parsed_text[:_REVISION_PREVIEW_CHARS],
        }
        for r in result.scalars().all()
    ]
    return {"document_id": str(document_id), "revisions": revisions}


@router.post("/{document_id}/revisions/{revision_id}/restore")
async def restore_document_revision(
    document_id: UUID,
    revision_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.pipeline.tasks.process import continue_processing

    doc = await db.scalar(select(Document).where(Document.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await check_document_access(db, doc, current_user, min_role="editor")
    if doc.status != "INDEXED":
        raise HTTPException(
            status_code=409, detail=f"Document is not indexed yet (status={doc.status})"
        )

    revision = await db.scalar(
        select(DocumentTextRevision).where(
            DocumentTextRevision.id == revision_id,
            DocumentTextRevision.document_id == document_id,
        )
    )
    if not revision:
        raise HTTPException(status_code=404, detail="Revision not found")

    db.add(
        DocumentTextRevision(
            document_id=document_id,
            source="RESTORE",
            parsed_text=revision.parsed_text,
            created_by=str(current_user.id),
        )
    )
    await db.commit()

    continue_processing.delay(str(document_id), edited_text=revision.parsed_text)
    return {"message": "Restore started", "status": "CHUNKING"}


@router.post("/{document_id}/retry")
async def retry_failed_document(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    doc = await db.scalar(select(Document).where(Document.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await check_document_access(db, doc, current_user, min_role="editor")
    if doc.status != "FAILED":
        raise HTTPException(
            status_code=409, detail=f"Document has not failed (status={doc.status})"
        )

    doc.status = "QUEUED"
    doc.error_message = None
    await db.commit()
    await _start_preprocess_workflow(db, doc)
    return {"message": "Retry started", "status": "QUEUED"}


@router.patch("/{document_id}/tags")
async def update_document_tags(
    document_id: UUID,
    body: DocumentTagsUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.qdrant_service import qdrant_service

    doc = await db.scalar(select(Document).where(Document.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await check_document_access(db, doc, current_user, min_role="editor")

    tags = [t.strip() for t in body.tags if t.strip()]
    doc.tags = tags or None
    await db.commit()

    # Push to already-indexed chunks immediately — no re-embedding needed for a
    # payload-only change.
    qdrant_service.set_payload_by_document(
        settings.qdrant_collection_name, str(document_id), {"tags": tags}
    )
    return {"tags": tags}


@router.post("/{document_id}/tags/accept-suggestion")
async def accept_tag_suggestion(
    document_id: UUID,
    body: DocumentTagSuggestionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Promotes one LLM-suggested tag into the user-managed tag list. Reuses
    update_document_tags' Qdrant sync since the result is indistinguishable
    from a manually-added tag.

    Deliberately leaves suggested_tags untouched (사용자 확인 2026-07-20,
    "추천 태그... 계속 유지하고 싶다") — a promoted suggestion stays visible in
    the 추천 태그 list instead of disappearing, so the frontend renders it in
    an "already added" state (see DocumentDetailPage.tsx) rather than losing
    it. Only dismiss_tag_suggestion actually removes an entry."""
    from app.services.qdrant_service import qdrant_service

    doc = await db.scalar(select(Document).where(Document.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await check_document_access(db, doc, current_user, min_role="editor")

    tags = [*(doc.tags or [])]
    if body.tag not in tags:
        tags.append(body.tag)
    doc.tags = tags
    await db.commit()

    qdrant_service.set_payload_by_document(
        settings.qdrant_collection_name, str(document_id), {"tags": tags}
    )
    return {"tags": doc.tags, "suggested_tags": doc.suggested_tags}


@router.post("/{document_id}/tags/dismiss-suggestion")
async def dismiss_tag_suggestion(
    document_id: UUID,
    body: DocumentTagSuggestionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Drops one LLM-suggested tag without adding it to tags. Never touches
    Qdrant — suggestions are never written there in the first place."""
    doc = await db.scalar(select(Document).where(Document.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await check_document_access(db, doc, current_user, min_role="editor")

    doc.suggested_tags = [t for t in (doc.suggested_tags or []) if t != body.tag] or None
    await db.commit()
    return {"suggested_tags": doc.suggested_tags}


@router.get("/{document_id}/images", response_model=DocumentImagesResponse)
async def get_document_images(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.storage import storage_service

    doc = await db.scalar(select(Document).where(Document.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await check_document_access(db, doc, current_user, min_role="viewer")
    images = [
        {
            "page_number": record["page_number"],
            "text": record.get("text", ""),
            "url": storage_service.get_presigned_url(
                settings.minio_bucket_artifacts, record["storage_key"]
            ),
        }
        for record in (doc.images or [])
    ]
    return {"document_id": str(doc.id), "images": images}


@router.get("/{document_id}/preview")
async def get_document_preview(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Original-view URL for the 원문 대조 tab: PDFs get their presigned
    original (browser-native viewer); DOCX/HWP/HWPX get converted to a real
    PDF via LibreOffice headless (falls back to a converted-HTML preview if
    conversion fails). Conversion is synchronous on first request, then
    cached in the artifacts bucket."""
    import asyncio

    from app.services.document_service import get_download_url
    from app.services.preview_service import preview_url_for

    doc = await db.scalar(select(Document).where(Document.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await check_document_access(db, doc, current_user, min_role="viewer")

    if doc.original_filename.lower().endswith(".pdf"):
        return {"url": get_download_url(doc.minio_key), "kind": "pdf", "approximate": False}

    url, kind, approximate = await asyncio.to_thread(
        preview_url_for, str(doc.id), doc.original_filename, doc.minio_key
    )
    if url is None:
        raise HTTPException(status_code=422, detail="이 형식은 원문 미리보기를 지원하지 않습니다")
    return {"url": url, "kind": kind, "approximate": approximate}


@router.get("/{document_id}/pages-text")
async def get_document_pages_text(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Per-page text powering page-synced navigation in the 원문 대조 tab.
    Native PDFs use parsed_text split via page_map (real page boundaries from
    the source). DOCX/HWP/HWPX have no such boundaries, so their pages come
    from extracting text directly out of the generated preview PDF instead —
    that pagination is the only page structure that actually exists for
    those formats."""
    import asyncio

    from app.services.preview_service import pdf_pages_text_for

    doc = await db.scalar(select(Document).where(Document.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await check_document_access(db, doc, current_user, min_role="viewer")

    if not doc.original_filename.lower().endswith(".pdf"):
        pages = await asyncio.to_thread(pdf_pages_text_for, str(doc.id))
        if pages:
            return {"document_id": str(doc.id), "pages": pages}

    text = doc.parsed_text or ""
    pages = []
    start = 0
    for end_offset, page_number in doc.page_map or []:
        pages.append({"page_number": page_number, "text": text[start:end_offset]})
        start = end_offset
    if not pages and text:
        pages = [{"page_number": 1, "text": text}]
    return {"document_id": str(doc.id), "pages": pages}


@router.get("/{document_id}/download", response_model=DocumentDownloadResponse)
async def get_document_download_url(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.document_service import get_download_url

    doc = await db.scalar(select(Document).where(Document.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await check_document_access(db, doc, current_user, min_role="viewer")
    return {"url": get_download_url(doc.minio_key)}


@router.get("/{document_id}/error")
async def get_document_error(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    doc = await db.scalar(select(Document).where(Document.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await check_document_access(db, doc, current_user, min_role="viewer")
    if doc.status != "FAILED":
        raise HTTPException(status_code=400, detail="Document has not failed")
    return {
        "document_id": doc.id,
        "status": doc.status,
        "error_message": doc.error_message,
        "failed_at": doc.updated_at,
    }
