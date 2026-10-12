import asyncio
import hashlib
import logging
from uuid import UUID, uuid4

from app.api.v1.deps import get_current_user
from app.api.v1.endpoints.documents.models import (
    BulkUploadResponse,
)
from app.api.v1.permissions import (
    check_collection_access,
    check_project_access,
)
from app.core.config import settings
from app.db.models.collection import Collection
from app.db.models.document import Document
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.document import (
    DocumentUploadResponse,
)
from app.services.document_storage import release_original
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()

_SUPPORTED_UPLOAD_SUFFIXES = {".pdf", ".docx", ".hwp", ".hwpx"}
# Safety caps for a ZIP-bulk upload — this endpoint decompresses attacker-
# controllable archive content in memory, so both entry count and total
# uncompressed size need hard limits (classic zip-bomb surface).
_ZIP_MAX_ARCHIVE_BYTES = 1024 * 1024 * 1024
_ZIP_MAX_ENTRIES = 200
_ZIP_MAX_ENTRY_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
_ZIP_MAX_TOTAL_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024


async def _resolve_preprocess_version_id(
    db: AsyncSession, collection_id: str | None, explicit_version_id: str | None = None,
    current_user: User | None = None,
):
    """업로드 다이얼로그에서 명시적으로 고른 workflow_version_id가 있으면 그것을
    최우선으로 쓰고(단, PREPROCESS 종류인지는 확인한다), 없으면
    Collection.default_workflow_id(+ default_workflow_version, null이면 항상
    최신 발행 버전) 순, 그마저도 없으면 시스템 표준 PREPROCESS 워크플로우의
    최신 발행 버전 — 통합 설계서 §13 Task 3 / §2 업로드 워크플로우 오버라이드."""
    from app.db.models.workflow import WorkflowDefinition, WorkflowVersion

    if explicit_version_id:
        # Defect 8: Validate UUID format and access rights
        try:
            version_uuid = UUID(explicit_version_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="잘못된 워크플로우 버전 ID 형식입니다")

        version = await db.get(WorkflowVersion, version_uuid)
        if version is None:
            raise HTTPException(status_code=400, detail="지정한 워크플로우 버전을 찾을 수 없습니다")
        workflow = await db.get(WorkflowDefinition, version.workflow_id)
        if workflow is None or workflow.kind != "PREPROCESS":
            raise HTTPException(status_code=400, detail="전처리(PREPROCESS) 워크플로우 버전만 지정할 수 있습니다")

        # Defect 8: Check access rights on the workflow
        # System workflows (project_id=None) are always accessible
        # Project-specific workflows must have user access to the project
        if workflow.project_id is not None and current_user is not None:
            await check_project_access(db, str(workflow.project_id), current_user, min_role="viewer")

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
    skip_review: bool = False,
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
        current_user=None,  # Workflow access was already checked in upload handler
    )
    dictionary_version = await current_dictionary_version(db)

    run = WorkflowRun(
        version_id=version_id, document_id=document.id, status="QUEUED", trigger="UPLOAD",
        dictionary_version=dictionary_version, skip_review=skip_review,
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
        timeout_seconds = (block.config or {}).get("timeoutSeconds", 1800)
        run_workflow_step.apply_async(
            args=[str(run.id), str(block.id)], time_limit=timeout_seconds,
            queue=step_queue_for_block(block),
        )


async def _start_workflow_or_mark_failed(
    db: AsyncSession, document: Document, workflow_version_id: str | None, skip_review: bool,
) -> None:
    """`_start_preprocess_workflow`가 실패하면 문서를 QUEUED로 방치하지 않고 FAILED로
    기록한 뒤 원래 예외를 다시 던진다(업로드는 이미 커밋된 뒤라 사용자가 목록에서
    실패 사유를 보고 삭제/재처리할 수 있어야 한다)."""
    document_id = document.id
    try:
        await _start_preprocess_workflow(db, document, workflow_version_id, skip_review=skip_review)
    except Exception as exc:
        await db.rollback()
        message = exc.detail if isinstance(exc, HTTPException) else "처리를 시작하지 못했습니다."
        await db.execute(
            update(Document).where(Document.id == document_id)
            .values(status="FAILED", error_message=str(message)[:500])
        )
        await db.commit()
        raise


_GENERIC_CONTENT_TYPES = frozenset({"", "application/octet-stream"})
# 운영 컨테이너(python:3.11-slim)에는 시스템 MIME 테이블이 없어 mimetypes가 pdf 외의
# 지원 형식(docx/hwp/hwpx)을 모른다 — 지원 확장자는 명시적으로 지정한다.
_EXTENSION_CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".hwp": "application/x-hwp",
    ".hwpx": "application/haansofthwpx",
}


def _resolve_content_type(filename: str, declared: str | None) -> str:
    """MinIO에 저장할 Content-Type을 정한다.

    지원 확장자(pdf/docx/hwp/hwpx)는 클라이언트가 뭐라고 선언하든 확장자 기준 타입을 쓴다.
    원본은 앱과 다른 출처(MinIO)에서 인라인으로 렌더링되므로, `.pdf` 를 text/html 이나
    image/svg+xml 로 선언해 올리면 그 출처에서 스크립트가 실행될 수 있다. 그 외 확장자는
    클라이언트가 구체적인 타입을 보냈으면 존중하고, 없거나 octet-stream 이면 파일명으로 추정한다
    (octet-stream 으로 저장하면 nosniff 때문에 브라우저가 PDF 를 iframe 으로 렌더링하지 못한다)."""
    import mimetypes
    from pathlib import PurePath

    known = _EXTENSION_CONTENT_TYPES.get(PurePath(filename).suffix.lower())
    if known:
        return known
    if declared and declared not in _GENERIC_CONTENT_TYPES:
        return declared
    return mimetypes.guess_type(filename)[0] or "application/octet-stream"


async def _read_bounded(file: UploadFile, limit: int, too_large_detail: str) -> bytes:
    """업로드 본문을 상한+1바이트까지만 읽어, 거대한 요청이 메모리를 채우기 전에 413으로 끊는다."""
    content = await file.read(limit + 1)
    if len(content) > limit:
        raise HTTPException(status_code=413, detail=too_large_detail)
    return content


@router.post("/upload", response_model=DocumentUploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    collection_id: str | None = Form(None),
    skip_review: bool = Form(False),
    workflow_version_id: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from pathlib import PurePath

    from app.services.storage import storage_service

    if collection_id is not None:
        await check_collection_access(db, collection_id, current_user, min_role="editor")

    # Defect 4: Validate file size before storing (읽는 단계에서 상한을 강제한다)
    content = await _read_bounded(
        file, settings.max_upload_size_bytes,
        f"파일 크기가 너무 큽니다. 최대 {settings.max_upload_size_bytes // (1024*1024)}MB까지 업로드할 수 있습니다.",
    )

    # Defect 4: Validate extension
    safe_name = file.filename or "upload"
    ext = PurePath(safe_name).suffix.lower()
    if ext not in _SUPPORTED_UPLOAD_SUFFIXES:
        raise HTTPException(
            status_code=415,
            detail=f"지원하지 않는 파일 형식입니다. 지원 형식: {', '.join(_SUPPORTED_UPLOAD_SUFFIXES)}",
        )

    # Defect 4: Sanitize filename (remove path traversal)
    safe_name = PurePath(safe_name).name

    file_hash = hashlib.sha256(content).hexdigest()

    # Duplicate guard: the same bytes indexed twice in one collection produce
    # duplicate chunks that pollute retrieval. Delete the existing document
    # first if a re-index is intended. Scope to current user's documents only
    # to prevent cross-user information leakage.
    dup_filters = [
        Document.file_hash == file_hash,
        Document.created_by == str(current_user.id),
    ]
    if collection_id is not None:
        dup_filters.append(Document.collection_id == collection_id)
    else:
        # When no collection specified, only match uncollected documents
        dup_filters.append(Document.collection_id.is_(None))
    duplicate = await db.scalar(select(Document).where(*dup_filters).limit(1))
    if duplicate:
        # Generic message without filename to avoid leaking document details
        raise HTTPException(
            status_code=409,
            detail="동일한 파일이 이미 존재합니다. 다시 처리하려면 기존 문서를 먼저 삭제하세요.",
        )

    # Defect 1: Use per-document key to avoid sharing minio objects
    # Generate document ID upfront so it can be included in the minio key
    doc_id = uuid4()
    minio_key = f"{doc_id}/{safe_name}"
    content_type = _resolve_content_type(safe_name, file.content_type)

    try:
        await asyncio.to_thread(
            storage_service.upload_file,
            settings.minio_bucket_originals,
            minio_key,
            content,
            content_type,
        )
    except Exception as exc:
        # Defect 4: Don't leak exception details to client
        import logging
        logging.error(f"Failed to upload file to minio: {exc}")
        raise HTTPException(
            status_code=500,
            detail="파일 저장 중 오류가 발생했습니다.",
        )

    document = Document(
        id=doc_id,
        filename=safe_name,
        original_filename=safe_name,
        file_size=len(content),
        mime_type=content_type,
        file_hash=file_hash,
        minio_key=minio_key,
        status="QUEUED",
        created_by=str(current_user.id),
        collection_id=collection_id,
    )
    db.add(document)
    try:
        await db.commit()
    except Exception:
        # 객체는 이미 올라갔는데 행이 없으면 고아 원본이 남는다 — 되돌린다.
        await db.rollback()
        await release_original(db, storage_service, settings.minio_bucket_originals, minio_key)
        raise
    await db.refresh(document)

    await _start_workflow_or_mark_failed(db, document, workflow_version_id, skip_review)

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
    import zipfile
    from pathlib import PurePosixPath

    from app.services.storage import storage_service

    if collection_id is not None:
        await check_collection_access(db, collection_id, current_user, min_role="editor")

    zip_bytes = await _read_bounded(
        file, _ZIP_MAX_ARCHIVE_BYTES,
        f"ZIP 파일이 너무 큽니다. 최대 {_ZIP_MAX_ARCHIVE_BYTES // (1024*1024)}MB까지 업로드할 수 있습니다.",
    )
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
            logging.error(f"Failed to read zip entry {entry_name}: {exc}")
            results.append({"filename": entry_name, "status": "failed", "detail": "파일 읽기 실패"})
            continue

        file_hash = hashlib.sha256(content).hexdigest()
        # Scope duplicate check to current user's documents only
        dup_filters = [
            Document.file_hash == file_hash,
            Document.created_by == str(current_user.id),
        ]
        if collection_id is not None:
            dup_filters.append(Document.collection_id == collection_id)
        else:
            dup_filters.append(Document.collection_id.is_(None))
        duplicate = await db.scalar(select(Document).where(*dup_filters).limit(1))
        if duplicate:
            results.append({
                "filename": entry_name,
                "status": "duplicate",
                "document_id": duplicate.id,
                "detail": "동일한 파일이 이미 존재합니다.",
            })
            continue

        try:
            # Defect 1: Use per-document key
            doc_id = uuid4()
            minio_key = f"{doc_id}/{entry_name}"
            content_type = _resolve_content_type(entry_name, None)
            await asyncio.to_thread(
                storage_service.upload_file,
                settings.minio_bucket_originals, minio_key, content, content_type
            )

            document = Document(
                id=doc_id,
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
            try:
                await db.commit()
            except Exception:
                await db.rollback()
                await release_original(db, storage_service, settings.minio_bucket_originals, minio_key)
                raise
            await db.refresh(document)

            await _start_workflow_or_mark_failed(db, document, workflow_version_id, skip_review)
            results.append({"filename": entry_name, "status": "queued", "document_id": document.id})
            queued += 1
        except Exception as exc:
            await db.rollback()
            logging.error(f"Failed to upload zip entry {entry_name}: {exc}")
            results.append({"filename": entry_name, "status": "failed", "detail": "파일 업로드 실패"})

    return {"total_entries": len(entries), "queued": queued, "results": results}



