"""청크 합치기와 검토 대기 중(임베딩 전) 청크 수정 (2026-11-17 화면 검토 의견).

- 짧은 청크는 앞이나 뒤 청크에 붙여 하나로 만든다. 남는 청크는 다시 임베딩하고, 붙인 청크는 지운다.
- 품질 게이트에서 멈춘 문서(WAITING_REVIEW)는 청크가 아직 벡터 저장소에 없다. 이때는 Postgres의
  청크만 고친다. 승인 후 이어지는 rag_store 블록이 Postgres에서 청크 글을 읽어 임베딩하므로 그대로 반영된다.
"""
import asyncio
import logging
from uuid import UUID

from app.api.v1.deps import get_current_user
from app.api.v1.permissions import check_document_access
from app.core.config import settings
from app.db.models.document import Document
from app.db.models.document_chunk import DocumentChunk
from app.db.models.user import User
from app.db.session import get_db
from app.pipeline.blocks.quality_blocks import QualityCheckConfig
from app.schemas.document import ChunkMergeRequest
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)
router = APIRouter()

REVIEW_STATUS = "WAITING_REVIEW"
# 임베딩된 청크를 고칠 수 있는 상태. 처리 중에는 청크가 통째로 다시 만들어지므로 막는다
_EDITABLE_INDEXED_STATUSES = frozenset({"INDEXED", "ANALYZING"})
_MERGE_SEPARATOR = "\n"
_REEMBED_TIMEOUT_SECONDS = 60
# 품질 블록의 기본 기준과 같게 판단한다(짧은 청크 50자 미만, 긴 청크 2000자 초과)
_QUALITY_DEFAULTS = QualityCheckConfig()
_WARNING_KEYS = (("short_chunk_ids", "chunking_short"), ("long_chunk_ids", "chunking_long"))


def parse_chunk_id(chunk_id: str) -> UUID:
    try:
        return UUID(chunk_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail="잘못된 청크 ID 형식입니다")


async def is_review_draft(db: AsyncSession, doc: Document, chunk: DocumentChunk | None) -> bool:
    """검토 게이트에서 멈춰 아직 임베딩되지 않은 청크인가.

    승인하면 run이 먼저 RUNNING으로 바뀌고 문서 상태는 rag_store가 끝난 뒤에 바뀐다. 그 사이에
    rag_store가 읽어 가는 청크를 고치지 않도록 청크를 만든 run도 아직 멈춰 있는지 본다.
    """
    from app.db.models.workflow_run import WorkflowRun

    if chunk is None or doc.status != REVIEW_STATUS or chunk.embedded:
        return False
    run_status = await db.scalar(select(WorkflowRun.status).where(WorkflowRun.id == chunk.run_id))
    return run_status == REVIEW_STATUS


async def load_chunk(db: AsyncSession, document_id: UUID, chunk_id: UUID) -> DocumentChunk | None:
    return await db.scalar(
        select(DocumentChunk).where(DocumentChunk.id == chunk_id, DocumentChunk.document_id == document_id)
    )


def _still_flagged(key: str, text: str) -> bool:
    if key == "short_chunk_ids":
        return len(text) < _QUALITY_DEFAULTS.min_chunk_chars_warning
    return len(text) > _QUALITY_DEFAULTS.max_chunk_chars_warning


async def refresh_chunk_warnings(
    db: AsyncSession, doc: Document, *, removed: tuple[str, ...] = (), edited: dict[str, str] | None = None,
) -> None:
    """지운 청크와 길이 문제가 풀린 청크를 품질 보고서의 짧은/긴 청크 목록에서 뺀다."""
    from app.db.models.quality_report import QualityReport

    report = None
    if doc.active_run_id:
        report = await db.scalar(select(QualityReport).where(QualityReport.run_id == doc.active_run_id))
    if report is None:
        report = await db.scalar(
            select(QualityReport).where(QualityReport.document_id == doc.id)
            .order_by(desc(QualityReport.created_at)).limit(1)
        )
    if report is None or not report.metrics:
        return
    edited = edited or {}
    metrics = dict(report.metrics)
    warnings = list(report.warnings or [])
    categories = list(report.warning_categories or [])
    changed = False
    for key, category in _WARNING_KEYS:
        ids = metrics.get(key) or []
        kept = [
            i for i in ids
            if i not in removed and not (i in edited and not _still_flagged(key, edited[i]))
        ]
        if kept == ids:
            continue
        metrics[key] = kept
        changed = True
        if not kept and category in categories:
            idx = categories.index(category)
            categories.pop(idx)
            if idx < len(warnings):
                warnings.pop(idx)
    if changed:
        report.metrics = metrics
        report.warnings = warnings
        report.warning_categories = categories


async def relink_and_delete(db: AsyncSession, chunk: DocumentChunk) -> None:
    """청크를 지우고 앞뒤 청크의 링크를 서로 잇는다."""
    prev_id, next_id = chunk.prev_chunk_id, chunk.next_chunk_id
    if prev_id:
        await db.execute(update(DocumentChunk).where(DocumentChunk.id == prev_id).values(next_chunk_id=next_id))
    if next_id:
        await db.execute(update(DocumentChunk).where(DocumentChunk.id == next_id).values(prev_chunk_id=prev_id))
    await db.execute(delete(DocumentChunk).where(DocumentChunk.id == chunk.id))


async def _neighbour(db: AsyncSession, chunk: DocumentChunk, direction: str) -> DocumentChunk | None:
    """같은 처리 결과(run) 안에서 문서 순서상 바로 앞이나 뒤의 child 청크."""
    query = select(DocumentChunk).where(
        DocumentChunk.document_id == chunk.document_id,
        DocumentChunk.run_id == chunk.run_id,
        DocumentChunk.chunk_tier == "child",
    )
    if direction == "prev":
        query = query.where(DocumentChunk.chunk_order < chunk.chunk_order).order_by(DocumentChunk.chunk_order.desc())
    else:
        query = query.where(DocumentChunk.chunk_order > chunk.chunk_order).order_by(DocumentChunk.chunk_order.asc())
    return await db.scalar(query.limit(1))


def _merge_location(kept: DocumentChunk, removed: DocumentChunk) -> None:
    """합친 청크가 두 청크의 쪽과 원문 범위를 모두 덮게 한다."""
    pages = [p for p in (kept.page_start, kept.page_end, removed.page_start, removed.page_end) if p is not None]
    if pages:
        kept.page_start, kept.page_end = min(pages), max(pages)
    spans = [s for s in (kept.span_start, removed.span_start) if s is not None]
    ends = [s for s in (kept.span_end, removed.span_end) if s is not None]
    if spans:
        kept.span_start = min(spans)
    if ends:
        kept.span_end = max(ends)


async def _indexed_texts(
    document_id: UUID, kept_id: str, removed_id: str,
) -> tuple[tuple[str, bool], tuple[str, bool]]:
    """임베딩된 청크는 화면에서 고친 글이 벡터 저장소에만 있을 수 있어 그쪽 글을 기준으로 한다.

    각 청크의 (글, 검색 제외 여부)를 돌려준다.
    """
    from app.services.qdrant_service import qdrant_service

    found = []
    for point_id in (kept_id, removed_id):
        point = await asyncio.to_thread(qdrant_service.get_point, settings.qdrant_collection_name, point_id)
        if point is None or point["payload"].get("document_id") != str(document_id):
            raise HTTPException(status_code=404, detail="합칠 청크를 검색 색인에서 찾지 못했습니다. 문서를 다시 처리해 주세요")
        payload = point["payload"]
        found.append((payload.get("text", ""), bool(payload.get("disabled", False))))
    return found[0], found[1]


async def _reembed(document_id: UUID, chunk_id: str, text: str) -> None:
    from app.pipeline.tasks.chunks import update_chunk_text

    result = update_chunk_text.delay(str(document_id), chunk_id, text)
    try:
        outcome = await asyncio.to_thread(result.get, timeout=_REEMBED_TIMEOUT_SECONDS)
    except Exception as exc:  # noqa: BLE001
        logger.error("청크 합치기 재임베딩 실패 document=%s chunk=%s: %s", document_id, chunk_id, exc)
        raise HTTPException(status_code=504, detail="합친 청크를 다시 임베딩하지 못했습니다. 잠시 뒤 다시 시도하세요") from exc
    if outcome.get("status") != "OK":
        raise HTTPException(status_code=404, detail="합칠 청크를 검색 색인에서 찾지 못했습니다. 문서를 다시 처리해 주세요")


@router.post("/{document_id}/chunks/{chunk_id}/merge")
async def merge_document_chunk(
    document_id: UUID,
    chunk_id: str,
    body: ChunkMergeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """이 청크를 앞 청크 끝(prev)이나 뒤 청크 앞(next)에 붙이고 이 청크는 지운다."""
    chunk_uuid = parse_chunk_id(chunk_id)
    # 문서 행을 잠가 같은 문서의 합치기를 한 번에 하나씩 처리한다. 이웃 청크를 동시에 합치면
    # 한쪽이 지운 청크에 다른 쪽이 글을 붙여 글이 사라지거나 벡터만 남을 수 있다
    doc = await db.scalar(select(Document).where(Document.id == document_id).with_for_update())
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await check_document_access(db, doc, current_user, min_role="editor")

    chunk = await load_chunk(db, document_id, chunk_uuid)
    if chunk is None or chunk.chunk_tier != "child":
        raise HTTPException(status_code=404, detail="Chunk not found")
    is_draft = await is_review_draft(db, doc, chunk)
    if not is_draft and not (doc.status in _EDITABLE_INDEXED_STATUSES and chunk.embedded):
        raise HTTPException(status_code=409, detail="문서 처리가 끝났거나 검토 대기 중일 때만 청크를 합칠 수 있습니다")

    neighbour = await _neighbour(db, chunk, body.direction)
    if neighbour is None:
        side = "앞" if body.direction == "prev" else "뒤"
        raise HTTPException(status_code=409, detail=f"{side}에 합칠 청크가 없습니다")
    if neighbour.embedded != chunk.embedded:
        raise HTTPException(status_code=409, detail="임베딩 상태가 다른 청크끼리는 합칠 수 없습니다. 문서를 다시 처리해 주세요")
    # 개인정보 때문에 색인에서 뺀 청크를 일반 청크와 합치면 그 글이 검색되거나 일반 글이 같이 사라진다
    if bool(neighbour.excluded_pii) != bool(chunk.excluded_pii):
        raise HTTPException(status_code=409, detail="개인정보로 색인에서 제외한 청크와 일반 청크는 합칠 수 없습니다")

    kept_id, removed_id = str(neighbour.id), str(chunk.id)
    if is_draft:
        kept_text, removed_text = neighbour.chunk_text, chunk.chunk_text
    else:
        (kept_text, kept_disabled), (removed_text, removed_disabled) = await _indexed_texts(
            document_id, kept_id, removed_id,
        )
        # 검색 제외한 청크를 검색되는 청크와 합치면 제외한 글이 다시 검색되거나 그 반대가 된다
        if kept_disabled != removed_disabled:
            raise HTTPException(status_code=409, detail="검색 제외 상태가 다른 청크끼리는 합칠 수 없습니다")
    parts = (kept_text, removed_text) if body.direction == "prev" else (removed_text, kept_text)
    merged_text = _MERGE_SEPARATOR.join(p for p in parts if p)

    if not is_draft:
        await _reembed(document_id, kept_id, merged_text)

    neighbour.chunk_text = merged_text
    neighbour.char_count = len(merged_text)
    neighbour.edited = True
    _merge_location(neighbour, chunk)
    await refresh_chunk_warnings(db, doc, removed=(removed_id,), edited={kept_id: merged_text})
    await relink_and_delete(db, chunk)
    await db.commit()

    if not is_draft:
        from app.services.qdrant_service import qdrant_service

        try:
            await asyncio.to_thread(qdrant_service.delete_points, settings.qdrant_collection_name, [removed_id])
        except Exception as exc:  # noqa: BLE001
            # DB는 이미 정리됐다. 남은 점은 다음 재처리 때 문서 단위 정리로 지워진다
            logger.warning("합친 청크의 벡터 삭제 실패 document=%s chunk=%s: %s", document_id, removed_id, exc)

    return {"message": "Chunks merged", "kept_chunk_id": kept_id, "removed_chunk_id": removed_id}
