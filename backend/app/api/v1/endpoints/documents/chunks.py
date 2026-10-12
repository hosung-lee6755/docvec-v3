import asyncio
import logging
from uuid import UUID

from app.api.v1.deps import get_current_user
from app.api.v1.endpoints.documents.processing import _resolve_display_run_id
from app.api.v1.endpoints.documents.upload import _start_workflow_or_mark_failed
from app.api.v1.permissions import (
    check_document_access,
)
from app.core.config import settings
from app.db.models.document import Document
from app.db.models.document_revision import DocumentTextRevision
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.document import (
    ChunkUpdateRequest,
    DocumentChunksResponse,
    DocumentRevisionsResponse,
)
from app.services.document_state import claim_document_status as _claim_document_status
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()

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

    # 메타 정보 생성 설계서(2026-07-23) Phase 4 — token_count/chunk_type/
    # keywords/embedding_model/element_id/prev_chunk_id/next_chunk_id/
    # workflow_version/dictionary_version은 Postgres DocumentChunk에만 있고
    # Qdrant 페이로드에는 없어, 히트 경로에서도 이 조회 결과를 병합한다.
    from app.db.models.document_chunk import DocumentChunk as _DocumentChunkModel

    pg_chunks_by_id: dict[str, _DocumentChunkModel] = {}
    if run_id:
        pg_rows = (
            await db.scalars(
                select(_DocumentChunkModel).where(
                    _DocumentChunkModel.document_id == document_id,
                    _DocumentChunkModel.run_id == run_id,
                    # Chunk 계층형 Parent Retrieval(메타 정보 생성.txt 3절, Phase 9) —
                    # 여기서는 parent 행도 함께 조회해둔다(아래 _pg_fields()가
                    # child의 parent_chunk_id로 parent 텍스트를 찾아야 하므로).
                    # parent 자체는 "청크 #N" 카드로는 절대 렌더링되지 않는다 —
                    # Qdrant 히트 목록(임베딩 대상만 있음)과 WAITING_REVIEW 폴백
                    # 목록(아래에서 chunk_tier=="child"로 필터링) 둘 다 parent를
                    # 만들어내지 않기 때문.
                )
            )
        ).all()
        pg_chunks_by_id = {str(c.id): c for c in pg_rows}

    def _pg_fields(chunk_id: str) -> dict:
        c = pg_chunks_by_id.get(chunk_id)
        if c is None:
            return {}
        parent = pg_chunks_by_id.get(str(c.parent_chunk_id)) if c.parent_chunk_id else None
        return {
            "token_count": c.token_count,
            "chunk_type": c.chunk_type,
            "keywords": c.keywords,
            "embedding_model": c.embedding_model,
            "element_id": c.element_id,
            "prev_chunk_id": str(c.prev_chunk_id) if c.prev_chunk_id else None,
            "next_chunk_id": str(c.next_chunk_id) if c.next_chunk_id else None,
            "workflow_version": c.workflow_version,
            "dictionary_version": c.dictionary_version,
            "section_path": c.section_path,
            # 메타 정보 생성.txt 3절 후속(2026-07-24) — heading_path는
            # section_path와 동일한 데이터라 스펙 필드명으로만 별도 노출
            # (신규 컬럼 아님).
            "heading_path": c.section_path,
            # Parent Retrieval(Phase 9) — "상위 청크 보기" 토글용. parent 자체는
            # 목록에 노출되지 않으므로 child 응답에 텍스트를 인라인으로 실어준다.
            "parent_chunk_text": parent.chunk_text if parent else None,
            "language": c.language,
            "source_file": c.source_file,
            "version": c.version,
        }

    hits = qdrant_service.scroll_by_document(str(document_id))
    # Filter to the current run only. Qdrant points from prior/deleted runs persist
    # in the vector store even though their rows are gone (workflow_runs FK CASCADE
    # only touches Postgres document_chunks, not Qdrant vectors). Without filtering,
    # orphaned vectors from older runs cause chunk counts to diverge between the
    # RAG status and quality tabs.
    hits = [h for h in hits if h["payload"].get("workflow_run_id") == run_id]
    hits.sort(key=lambda h: h["payload"].get("chunk_index", 0))

    if not hits:
        # rag_store (embedding + Qdrant upload) runs downstream of review gates,
        # so documents stuck at WAITING_REVIEW have Postgres document_chunks rows
        # (already created by chunk_split) but no Qdrant vectors yet. Use Postgres
        # as fallback source per DocumentChunk design intent, but mark items with
        # embedded=False so the UI disables edit/delete (Qdrant-only operations).
        pg_chunks = (
            await db.scalars(
                select(_DocumentChunkModel)
                .where(
                    _DocumentChunkModel.document_id == document_id, _DocumentChunkModel.run_id == run_id,
                    # Phase 9 — parent 행은 청크 목록에 노출하지 않는다.
                    _DocumentChunkModel.chunk_tier == "child",
                )
                .order_by(_DocumentChunkModel.chunk_order)
            )
        ).all() if run_id else []
        total_chunks = len(pg_chunks)
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
                "total_chunks": total_chunks,
                "char_count": len(c.chunk_text),
                **_pg_fields(str(c.id)),
            }
            for c in pg_chunks
        ]
        return {"document_id": str(document_id), "chunks": chunks}

    hit_counts = await asyncio.to_thread(get_hit_counts, [h["id"] for h in hits])
    total_chunks = len(hits)
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
            "total_chunks": total_chunks,
            "char_count": len(h["payload"].get("text", "")),
            **_pg_fields(h["id"]),
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
    from app.services.qdrant_service import qdrant_service

    doc = await db.scalar(select(Document).where(Document.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await check_document_access(db, doc, current_user, min_role="editor")

    # 요청 형태 검증은 Qdrant I/O보다 먼저 — 잘못된 요청이 외부 호출을 일으키지 않게 한다.
    if body.disabled is None and body.text is None:
        raise HTTPException(status_code=422, detail="업데이트할 필드를 지정하세요")
    if body.disabled is not None and body.text is not None:
        # Defect G: Both fields together is ambiguous, reject
        raise HTTPException(status_code=400, detail="disabled와 text를 동시에 수정할 수 없습니다")
    if body.text is not None and not body.text.strip():
        raise HTTPException(status_code=422, detail="청크 텍스트는 비어 있을 수 없습니다")

    # Defect E: Wrap blocking I/O in asyncio.to_thread
    point = await asyncio.to_thread(
        qdrant_service.get_point, settings.qdrant_collection_name, chunk_id
    )
    if point is None or point["payload"].get("document_id") != str(document_id):
        raise HTTPException(status_code=404, detail="Chunk not found")

    if body.disabled is not None:
        # Defect E: Wrap in asyncio.to_thread
        await asyncio.to_thread(
            qdrant_service.set_point_payload,
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
            # Defect G: Don't expose raw exception text
            logging.error(f"Failed to re-embed chunk: {exc}")
            raise HTTPException(status_code=504, detail="청크 재임베딩 중 오류가 발생했습니다") from exc
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

    # Defect G: Validate chunk_id is a valid UUID format
    try:
        chunk_uuid = UUID(chunk_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail="잘못된 청크 ID 형식입니다")

    doc = await db.scalar(select(Document).where(Document.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await check_document_access(db, doc, current_user, min_role="editor")

    # Defect E: Wrap blocking I/O in asyncio.to_thread
    point = await asyncio.to_thread(
        qdrant_service.get_point, settings.qdrant_collection_name, chunk_id
    )
    if point is None or point["payload"].get("document_id") != str(document_id):
        raise HTTPException(status_code=404, detail="Chunk not found")

    # Defect G: Delete from DB first (atomic), then Qdrant (idempotent)
    # If DB delete fails, Qdrant point is untouched and retry works
    # If Qdrant delete fails, DB is already clean

    # document_chunks is the first-class source of truth (§4.6) — deleting only
    # the Qdrant point left this row behind forever, stale and still counted
    # by anything that queries document_chunks directly.
    await db.execute(delete(DocumentChunk).where(DocumentChunk.id == chunk_id))

    # If this chunk was the one a chunking warning pointed at, drop it from the
    # report so a resolved issue stops showing as still needing review.
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

    # Defect G: Delete from Qdrant AFTER DB commit (idempotent cleanup)
    # If Qdrant delete fails, DB is already clean and retry is safe
    try:
        await asyncio.to_thread(
            qdrant_service.delete_points, settings.qdrant_collection_name, [chunk_id]
        )
    except Exception as exc:
        logging.warning(f"Failed to delete chunk from Qdrant: {exc}")

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
    seen_status = doc.status  # rollback이 doc을 만료시키므로 먼저 읽어 둔다
    if not await _claim_document_status(db, document_id, "FAILED", "QUEUED", error_message=None):
        await db.rollback()
        raise HTTPException(
            status_code=409, detail=f"Document has not failed (status={seen_status})"
        )
    await db.commit()
    await db.refresh(doc)
    await _start_workflow_or_mark_failed(db, doc, None, False)
    return {"message": "Retry started", "status": "QUEUED"}



