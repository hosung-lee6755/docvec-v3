import hashlib
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import asc, delete, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user
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
from app.schemas.document import (
    ChunkUpdateRequest,
    DocumentChunksResponse,
    DocumentContentResponse,
    DocumentDownloadResponse,
    DocumentImagesResponse,
    DocumentListResponse,
    DocumentProceedRequest,
    DocumentReprocessRequest,
    DocumentResponse,
    DocumentRevisionsResponse,
    DocumentTablesResponse,
    DocumentTagsUpdateRequest,
    DocumentUploadResponse,
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


@router.post("/upload", response_model=DocumentUploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    collection_id: str | None = Form(None),
    skip_review: bool = Form(False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.pipeline.tasks.pipeline import create_processing_chain
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

    create_processing_chain(str(document.id), skip_review=skip_review).delay()

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

    from app.pipeline.tasks.pipeline import create_processing_chain
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

            create_processing_chain(str(document.id), skip_review=skip_review).delay()
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
    doc_ids = [doc.id for doc in docs]
    if doc_ids:
        await db.execute(delete(ProcessingJob).where(ProcessingJob.document_id.in_(doc_ids)))
    for doc in docs:
        qdrant_service.delete_by_document(settings.qdrant_collection_name, str(doc.id))
        storage_service.delete_file(settings.minio_bucket_originals, doc.minio_key)
        for record in doc.images or []:
            storage_service.delete_file(settings.minio_bucket_artifacts, record["storage_key"])
        await db.delete(doc)
    await db.commit()
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
    await db.execute(delete(ProcessingJob).where(ProcessingJob.document_id == document_id))
    qdrant_service.delete_by_document(settings.qdrant_collection_name, str(doc.id))
    storage_service.delete_file(settings.minio_bucket_originals, doc.minio_key)
    for record in doc.images or []:
        storage_service.delete_file(settings.minio_bucket_artifacts, record["storage_key"])
    await db.delete(doc)
    await db.commit()
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
    from app.pipeline.tasks.process import continue_processing

    doc = await db.scalar(select(Document).where(Document.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await check_document_access(db, doc, current_user, min_role="editor")
    if doc.status != "INDEXED":
        raise HTTPException(
            status_code=409,
            detail=f"Document is not indexed yet (status={doc.status})",
        )

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

    hits = qdrant_service.scroll_by_document(str(document_id))
    hits.sort(key=lambda h: h["payload"].get("chunk_index", 0))
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
    from app.services.qdrant_service import qdrant_service

    doc = await db.scalar(select(Document).where(Document.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await check_document_access(db, doc, current_user, min_role="editor")

    point = qdrant_service.get_point(settings.qdrant_collection_name, chunk_id)
    if point is None or point["payload"].get("document_id") != str(document_id):
        raise HTTPException(status_code=404, detail="Chunk not found")

    qdrant_service.delete_points(settings.qdrant_collection_name, [chunk_id])
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
    from app.pipeline.tasks.pipeline import create_processing_chain

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
    create_processing_chain(str(document_id)).delay()
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
