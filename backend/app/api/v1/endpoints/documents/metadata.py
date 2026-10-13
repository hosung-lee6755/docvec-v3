import asyncio
import logging
from uuid import UUID

from app.api.v1.deps import get_current_user
from app.api.v1.permissions import (
    check_document_access,
)
from app.core.config import settings
from app.db.models.document import Document
from app.db.models.document_chunk import DocumentChunk
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.document import (
    DocumentDownloadResponse,
    DocumentImagesResponse,
    DocumentMetadataUpdateRequest,
    DocumentResponse,
    DocumentTagSuggestionRequest,
    DocumentTagsUpdateRequest,
)
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()

# 자동 생성되며 사용자가 수정하면 재처리에서 보호되는 필드(user_edited_fields 대상).
_AUTO_FIELDS = frozenset({"title", "language", "category"})

async def _sync_tags_to_index(doc: Document, tags: list[str]) -> None:
    """이미 색인된 청크의 tags payload를 Postgres 저장 직후 맞춘다(재임베딩 불필요).

    Postgres가 정본이라 저장은 이미 끝난 상태다. 아직 색인 전(컬렉션이 없을 수도 있음)이면
    색인 시점에 doc.tags가 반영되므로 실패를 기록만 하고 넘어가고, 색인된 문서의 동기화
    실패는 사용자가 재시도할 수 있도록 502로 알린다(재시도해도 같은 결과 — 멱등)."""
    from app.services.qdrant_service import qdrant_service

    try:
        await asyncio.to_thread(
            qdrant_service.set_payload_by_document,
            settings.qdrant_collection_name, str(doc.id), {"tags": tags},
        )
    except Exception as exc:
        logging.warning("태그 인덱스 동기화 실패: document=%s", doc.id, exc_info=True)
        if doc.status == "INDEXED":
            raise HTTPException(
                status_code=502,
                detail="태그는 저장되었지만 검색 인덱스에 반영하지 못했습니다. 잠시 후 다시 시도하세요.",
            ) from exc


@router.patch("/{document_id}/tags")
async def update_document_tags(
    document_id: UUID,
    body: DocumentTagsUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    doc = await db.scalar(select(Document).where(Document.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await check_document_access(db, doc, current_user, min_role="editor")

    # 공백 제거 + 중복 제거(입력 순서 유지) — 같은 태그가 두 번 저장/필터되지 않게 한다.
    tags = list(dict.fromkeys(t.strip() for t in body.tags if t.strip()))
    doc.tags = tags or None
    await db.commit()

    await _sync_tags_to_index(doc, tags)
    return {"tags": tags}


@router.patch("/{document_id}/metadata", response_model=DocumentResponse)
async def update_document_metadata(
    document_id: UUID,
    body: DocumentMetadataUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """메타 정보 생성 설계서(2026-07-23) Phase 2 — author/organization/
    security_level/source_system은 문서 내용에서 자동 생성할 수 없어(사용자
    확인 2026-07-23), 이 엔드포인트를 통해 사용자가 입력한 값만 저장한다.
    `exclude_unset`으로 요청에 실제로 포함된 필드만 갱신 — 나머지 필드는
    건드리지 않는다(부분 업데이트)."""
    doc = await db.scalar(select(Document).where(Document.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await check_document_access(db, doc, current_user, min_role="editor")

    updates = body.model_dump(exclude_unset=True)
    resets = set(updates.pop("reset_fields", None) or [])
    edited = list(doc.user_edited_fields or [])
    for field, value in updates.items():
        if field in _AUTO_FIELDS:
            value = value.strip() if isinstance(value, str) else value
            if not value:  # 값을 비우면 자동값으로 되돌리는 것과 같다
                resets.add(field)
                continue
            if field not in edited:
                edited.append(field)
        setattr(doc, field, value)
    for field in resets:
        setattr(doc, field, None)
        edited = [f for f in edited if f != field]
    doc.user_edited_fields = edited or None

    if "language" in updates or "language" in resets:
        await db.execute(
            update(DocumentChunk).where(DocumentChunk.document_id == doc.id).values(language=doc.language)
        )
    await db.commit()
    await db.refresh(doc)
    return doc


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

    Deliberately leaves suggested_tags untouched — a promoted suggestion stays visible in
    the 추천 태그 list instead of disappearing, so the frontend renders it in
    an "already added" state (see DocumentDetailPage.tsx) rather than losing
    it. Only dismiss_tag_suggestion actually removes an entry."""
    doc = await db.scalar(select(Document).where(Document.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await check_document_access(db, doc, current_user, min_role="editor")

    tags = [*(doc.tags or [])]
    if body.tag not in tags:
        tags.append(body.tag)
    doc.tags = tags
    await db.commit()

    await _sync_tags_to_index(doc, tags)
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
    # Docling 경로에서만 의미 있음 — elements가 없는(legacy 엔진) 문서는 None이라
    # 프론트가 안내 문구를 아예 표시하지 않는다. detected_count가 len(images)보다
    # 크면 작은/중복 이미지가 _recognize_document_images(process.py)에서
    # 필터링된 것이다.
    detected_count = (
        sum(1 for el in doc.elements if el.get("type") == "picture")
        if doc.elements is not None else None
    )
    return {"document_id": str(doc.id), "images": images, "detected_count": detected_count}


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

