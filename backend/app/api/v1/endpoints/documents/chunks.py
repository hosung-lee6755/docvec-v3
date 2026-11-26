import asyncio
import logging
from uuid import UUID

from app.api.v1.deps import get_current_user
from app.api.v1.endpoints.documents.chunk_edits import (
    REVIEW_STATUS,
    is_review_draft,
    load_chunk,
    refresh_chunk_warnings,
    relink_and_delete,
)
from app.api.v1.endpoints.documents.processing import _resolve_tab_run_id
from app.api.v1.endpoints.documents.upload import _start_workflow_or_mark_failed
from app.api.v1.permissions import (
    check_document_access,
)
from app.core.config import settings
from app.db.models.document import Document
from app.db.models.document_revision import (
    INTERNAL_REVISION_SOURCES,
    NORMALIZED_REVISION_SOURCE,
    DocumentTextRevision,
)
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.document import (
    ChunkUpdateRequest,
    DocumentChunksResponse,
    DocumentRevisionsResponse,
)
from app.services.document_state import claim_document_status as _claim_document_status
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


async def _review_draft_or_none(db: AsyncSession, doc: Document, document_id: UUID, chunk_id: str):
    """검토 게이트에서 멈춘 문서의 아직 임베딩되지 않은 청크면 그 행을, 아니면 None을 돌려준다."""
    if doc.status != REVIEW_STATUS:
        return None
    try:
        chunk_uuid = UUID(chunk_id)
    except (ValueError, TypeError):
        return None
    chunk = await load_chunk(db, document_id, chunk_uuid)
    if chunk is None or chunk.chunk_tier != "child" or chunk.embedded:
        return None
    if not await is_review_draft(db, doc, chunk):
        # 검토를 승인해 임베딩이 진행 중이다. 이때 고치면 rag_store가 읽어 간 청크와 어긋난다
        raise HTTPException(status_code=409, detail="검토 승인 뒤 임베딩하는 중입니다. 끝난 뒤에 고쳐 주세요")
    return chunk
logger = logging.getLogger(__name__)

HIGHLIGHT_PAGE_HEADER = "X-Highlight-Page"
HIGHLIGHT_COUNT_HEADER = "X-Highlight-Count"


def _highlight_pdf_bytes(document_id: str, filename: str, minio_key: str) -> bytes | None:
    """위치를 그릴 PDF. PDF 원본은 그대로 쓰고, 다른 형식은 미리보기 PDF를 쓴다(없으면 만든다).
    미리보기가 PDF로 만들어지지 않는 형식(TXT, HTML 등)은 None이다."""
    from app.services.preview_service import cached_preview_pdf, preview_url_for
    from app.services.storage import storage_service

    if filename.lower().endswith(".pdf"):
        return storage_service.download_file(settings.minio_bucket_originals, minio_key)
    _url, kind, _approximate = preview_url_for(document_id, filename, minio_key)
    if kind != "pdf":
        return None
    return cached_preview_pdf(document_id)


@router.get("/{document_id}/chunks/{chunk_id}/highlight")
async def get_chunk_highlight(
    document_id: UUID,
    chunk_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """인용한 청크가 원문의 어느 자리인지 그 쪽을 그림(PNG)으로 돌려준다(전체 점검 1-7).
    근거 영역에 색을 입히고, 그린 쪽 번호와 표시한 영역 수를 응답 헤더에 싣는다."""
    from app.db.models.document_chunk import DocumentChunk
    from app.db.models.document_node import DocumentNode
    from app.services.audit import log_audit
    from app.services.citation_highlight import build_target, render_highlight

    doc = await db.scalar(select(Document).where(Document.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await check_document_access(db, doc, current_user, min_role="viewer")
    chunk = await db.scalar(
        select(DocumentChunk).where(DocumentChunk.id == chunk_id, DocumentChunk.document_id == document_id)
    )
    if chunk is None:
        raise HTTPException(status_code=404, detail="문서를 다시 처리해 이 인용의 위치 정보가 없습니다")

    node_ids = [i for i in (chunk.source_node_ids or []) if i]
    element_ids: list[str] = []
    if node_ids:
        element_ids = [
            e for e in (
                await db.scalars(select(DocumentNode.element_id).where(DocumentNode.id.in_(node_ids)))
            ).all() if e
        ]
    target = build_target(chunk, element_ids, doc.elements if isinstance(doc.elements, list) else None)

    pdf_bytes = await asyncio.to_thread(_highlight_pdf_bytes, str(doc.id), doc.original_filename, doc.minio_key)
    if pdf_bytes is None:
        raise HTTPException(status_code=422, detail="이 형식은 쪽 단위 위치 표시를 지원하지 않습니다")
    try:
        png, page_number, count = await asyncio.to_thread(render_highlight, pdf_bytes, target)
    except Exception as exc:  # noqa: BLE001 - 깨진 PDF 등
        logger.exception("citation highlight failed: document=%s chunk=%s", document_id, chunk_id)
        raise HTTPException(status_code=422, detail="원문 쪽을 그리지 못했습니다") from exc

    # 원문의 한 쪽을 그대로 내주므로 미리보기와 같은 조회 감사를 남긴다
    log_audit(db, str(current_user.id), "document.preview", "document", str(doc.id))
    await db.commit()
    return Response(
        content=png, media_type="image/png",
        headers={
            HIGHLIGHT_PAGE_HEADER: str(page_number), HIGHLIGHT_COUNT_HEADER: str(count),
            "Cache-Control": "private, no-store",
        },
    )


@router.get("/{document_id}/chunks/{chunk_id}/context")
async def get_chunk_context(
    document_id: UUID,
    chunk_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """쪽 그림을 그릴 수 없는 형식(TXT, MD, HTML, CSV 등)의 인용 위치 보기. 인용한 청크의 글과
    앞뒤 문맥, 절 경로, 쪽 범위를 돌려준다. 글은 개인정보 마스킹을 거친 NORMALIZED 스냅샷에서만 자른다.
    마스킹 전 parsed_text를 쓰면 인용이 가린 값이 둘레 글로 드러난다."""
    from app.db.models.document_chunk import DocumentChunk
    from app.services.audit import log_audit
    from app.services.citation_context import build_context

    doc = await db.scalar(select(Document).where(Document.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await check_document_access(db, doc, current_user, min_role="viewer")
    chunk = await db.scalar(
        select(DocumentChunk).where(DocumentChunk.id == chunk_id, DocumentChunk.document_id == document_id)
    )
    if chunk is None:
        raise HTTPException(status_code=404, detail="문서를 다시 처리해 이 인용의 위치 정보가 없습니다")
    normalized = await db.scalar(
        select(DocumentTextRevision.parsed_text)
        .where(
            DocumentTextRevision.document_id == document_id,
            DocumentTextRevision.source == NORMALIZED_REVISION_SOURCE,
        )
        .order_by(desc(DocumentTextRevision.created_at))
        .limit(1)
    )
    context = build_context(normalized, chunk)
    # 원문의 일부를 내주므로 미리보기와 같은 조회 감사를 남긴다
    log_audit(db, str(current_user.id), "document.preview", "document", str(doc.id))
    await db.commit()
    return {
        "chunk_id": str(chunk.id),
        **context,
        "section_path": chunk.section_path,
        "page_start": chunk.page_start,
        "page_end": chunk.page_end,
    }


def _table_refs(tables: list[dict] | None) -> dict[str, dict]:
    """documents.tables 의 표 id → 청크에 붙일 표 정보. 번호는 문서 안의 표 순서([표 N])다."""
    tables = tables or []
    number_of = {t.get("id"): i + 1 for i, t in enumerate(tables) if t.get("id")}
    refs: dict[str, dict] = {}
    for index, table in enumerate(tables):
        table_id = table.get("id")
        if not table_id:
            continue
        parent_id = table.get("parent_table_id") or None
        refs[table_id] = {
            "table_id": table_id,
            "table_number": index + 1,
            "title": table.get("title") or None,
            "parent_table_id": parent_id,
            "parent_table_number": number_of.get(parent_id) if parent_id else None,
            "parent_cell": table.get("parent_cell") if parent_id else None,
        }
    return refs


async def _table_ref_by_chunk(db: AsyncSession, chunks, tables: list[dict] | None) -> dict[str, dict]:
    """표 청크 id → 출처 표 정보(2026-11-20). 청크의 source_node_ids 가 가리키는 TABLE 노드의
    source_table_id 로 documents.tables 를 찾는다. 칸 안에서 떼어 낸 표면 바깥 표와 칸도 들어 있다."""
    from app.db.models.document_node import DocumentNode

    refs = _table_refs(tables)
    table_chunks = [c for c in chunks if (c.chunk_type or "").upper() == "TABLE" and c.source_node_ids]
    node_ids = {str(n) for c in table_chunks for n in c.source_node_ids}
    if not refs or not node_ids:
        return {}
    rows = await db.execute(
        select(DocumentNode.id, DocumentNode.source_table_id).where(
            DocumentNode.id.in_(node_ids), DocumentNode.source_table_id.isnot(None)
        )
    )
    table_of_node = {str(node_id): table_id for node_id, table_id in rows.all()}
    result: dict[str, dict] = {}
    for chunk in table_chunks:
        table_id = next((table_of_node[str(n)] for n in chunk.source_node_ids if str(n) in table_of_node), None)
        if table_id in refs:
            result[str(chunk.id)] = refs[table_id]
    return result


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
    # 청크를 실제로 만든 run(_resolve_tab_run_id) — 부분 재처리로 chunk_split 을 복사만 했으면 부모 run 을 본다.
    run_id = await _resolve_tab_run_id(db, doc, ("chunk_split",))

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
    table_by_chunk = await _table_ref_by_chunk(db, pg_chunks_by_id.values(), doc.tables)
    # 상위 청크에 child가 하나뿐이면 상위 청크가 곧 이 청크라 "상위 청크 보기"가 같은 글을 되풀이한다
    children_per_parent: dict[str, int] = {}
    for row in pg_chunks_by_id.values():
        if row.parent_chunk_id and row.chunk_tier == "child":
            key = str(row.parent_chunk_id)
            children_per_parent[key] = children_per_parent.get(key, 0) + 1

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
            "parent_chunk_text": (
                parent.chunk_text if parent and children_per_parent.get(str(parent.id), 0) > 1 else None
            ),
            "language": c.language,
            "source_file": c.source_file,
            "version": c.version,
            "table": table_by_chunk.get(chunk_id),
            # 원문 대조의 JSON 보기가 지금 쪽 글과 같은 구간의 청크를 고른다(2026-11-26). 여러 쪽에 걸친 청크는 끝 쪽까지 보인다
            "page_end": c.page_end,
            "span_start": c.span_start,
            "span_end": c.span_end,
        }

    hits = qdrant_service.scroll_by_document(str(document_id))
    # Filter to the current run only. Qdrant points from prior/deleted runs persist
    # in the vector store even though their rows are gone (workflow_runs FK CASCADE
    # only touches Postgres document_chunks, not Qdrant vectors). Without filtering,
    # orphaned vectors from older runs cause chunk counts to diverge between the
    # RAG status and quality tabs.
    # 벡터의 workflow_run_id 는 rag_store 를 실제로 돈 run 이다. 저장 단계부터 다시 돌리면 청크 행(chunk_split)은
    # 부모 run 에 있고 벡터는 새 run 에 적혀 있어 둘을 따로 푼다(같은 값으로 거르면 모든 청크가 "임베딩 안 됨").
    vector_run_id = await _resolve_tab_run_id(db, doc, ("rag_store",))
    hits = [h for h in hits if h["payload"].get("workflow_run_id") in {run_id, vector_run_id}]
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

    # 검토 대기 중인 문서의 청크는 아직 벡터 저장소에 없다. Postgres 청크만 고치면 승인 뒤 임베딩에 반영된다
    draft = await _review_draft_or_none(db, doc, document_id, chunk_id)
    if draft is not None:
        if body.disabled is not None:
            raise HTTPException(status_code=409, detail="검색 제외는 검토를 승인해 임베딩한 뒤에 할 수 있습니다")
        draft.chunk_text = body.text
        draft.char_count = len(body.text)
        draft.edited = True
        await refresh_chunk_warnings(db, doc, edited={str(draft.id): body.text})
        await db.commit()
        return {"message": "Chunk updated"}

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

    draft = await _review_draft_or_none(db, doc, document_id, chunk_id)
    if draft is not None:
        await refresh_chunk_warnings(db, doc, removed=(str(draft.id),))
        await relink_and_delete(db, draft)
        await db.commit()
        return {"message": "Chunk deleted"}

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
        .where(DocumentTextRevision.source.not_in(INTERNAL_REVISION_SOURCES))
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
            DocumentTextRevision.source.not_in(INTERNAL_REVISION_SOURCES),
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



