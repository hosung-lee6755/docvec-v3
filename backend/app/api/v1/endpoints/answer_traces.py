"""관리자용 답변 추적 조회 API(v3 마일스톤 2).

목록은 질의자·기간·근거 문서·근거 검증 결과로 거른다. 문서 id로 거르면 "이 문서를 근거로 쓴 답변"
역추적이 된다. 역추적은 그 관리자가 지금 볼 수 있는 문서와 접근 가능한 컬렉션으로만 할 수 있다.
볼 수 없는 문서로 거르면 빈 결과를 돌려준다(숨은 문서가 어떤 질문에 쓰였는지 알려 주지 않기 위해서다).
상세는 근거 청크마다 지금 그 관리자가 문서를 볼 수 있는지 다시 판정한다.
관리자도 문서 열람 규칙을 건너뛰지 못하므로, 볼 수 없는 문서의 현재 본문은 내려보내지 않는다.
상세 조회는 감사 로그(`answer_trace.view`)에 남는다.
"""
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, case, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user, require_admin
from app.db.models.answer_trace import AnswerTrace, AnswerTraceSource
from app.db.models.document import Document
from app.db.models.document_chunk import DocumentChunk
from app.db.models.user import User
from app.db.session import get_db
from app.services.access_policy import (
    build_access_context,
    load_document_facts,
    visible_document_ids,
)
from app.services.answer_trace import sha256_text
from app.services.audit import log_audit

router = APIRouter()

_QUERY_PREVIEW_LEN = 200

ACCESS_VISIBLE = "visible"
ACCESS_HIDDEN = "hidden"
ACCESS_DELETED = "deleted"


def _as_uuid(value: str | None) -> str | None:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError):
        return None


def _trace_filters(
    user_id: UUID | None,
    from_date: datetime | None,
    to_date: datetime | None,
    document_id: str | None,
    collection_id: str | None,
    grounding: str | None,
    status: str | None,
    cache_hit: bool | None,
) -> list:
    filters = []
    if user_id is not None:
        filters.append(AnswerTrace.user_id == str(user_id))
    if from_date is not None:
        filters.append(AnswerTrace.created_at >= from_date)
    if to_date is not None:
        filters.append(AnswerTrace.created_at <= to_date)
    if grounding is not None:
        filters.append(AnswerTrace.grounding == grounding)
    if status is not None:
        filters.append(AnswerTrace.status == status)
    if cache_hit is not None:
        filters.append(AnswerTrace.cache_hit.is_(cache_hit))
    if document_id is not None:
        filters.append(exists().where(and_(
            AnswerTraceSource.trace_id == AnswerTrace.id,
            AnswerTraceSource.document_id == document_id,
        )))
    if collection_id is not None:
        filters.append(or_(
            exists().where(and_(
                AnswerTraceSource.trace_id == AnswerTrace.id,
                AnswerTraceSource.collection_id == collection_id,
            )),
            AnswerTrace.scope_collection_id == collection_id,
        ))
    return filters


async def _lookup_allowed(db: AsyncSession, user: User, document_id: str | None, collection_id: str | None) -> bool:
    """역추적 필터가 관리자 자신이 볼 수 있는 대상인지 확인한다. 아니면 목록을 비운다."""
    if document_id is None and collection_id is None:
        return True
    ctx = await build_access_context(db, user)
    if collection_id is not None and collection_id not in ctx.collection_ids:
        return False
    if document_id is not None:
        facts = await load_document_facts(db, {document_id})
        return document_id in visible_document_ids(ctx, facts)
    return True


async def _source_counts(db: AsyncSession, trace_ids: list) -> dict[str, tuple[int, int]]:
    if not trace_ids:
        return {}
    rows = await db.execute(
        select(
            AnswerTraceSource.trace_id,
            func.count(),
            func.sum(case((AnswerTraceSource.cited.is_(True), 1), else_=0)),
        )
        .where(AnswerTraceSource.trace_id.in_(trace_ids))
        .group_by(AnswerTraceSource.trace_id)
    )
    return {str(t): (int(n), int(c or 0)) for t, n, c in rows.all()}


@router.get("/admin/answer-traces")
async def list_answer_traces(
    user_id: UUID | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    document_id: str | None = None,
    collection_id: str | None = None,
    grounding: str | None = None,
    status: str | None = None,
    cache_hit: bool | None = None,
    limit: int = Query(50, gt=0, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_admin(current_user)
    if document_id is not None:
        document_id = _as_uuid(document_id)
        if document_id is None:
            return {"total": 0, "items": []}
    if collection_id is not None:
        collection_id = _as_uuid(collection_id)
        if collection_id is None:
            return {"total": 0, "items": []}
    if not await _lookup_allowed(db, current_user, document_id, collection_id):
        return {"total": 0, "items": []}
    filters = _trace_filters(
        user_id, from_date, to_date, document_id, collection_id, grounding, status, cache_hit
    )

    total = await db.scalar(select(func.count(AnswerTrace.id)).where(*filters)) or 0
    traces = list((
        await db.scalars(
            select(AnswerTrace)
            .where(*filters)
            .order_by(AnswerTrace.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all())
    counts = await _source_counts(db, [t.id for t in traces])
    rows = [(t, *counts.get(str(t.id), (0, 0))) for t in traces]

    return {
        "total": total,
        "items": [
            {
                "id": str(t.id),
                "created_at": t.created_at,
                "user_id": str(t.user_id) if t.user_id else None,
                "username": t.username,
                "query": t.query[:_QUERY_PREVIEW_LEN],
                "status": t.status,
                "grounding": t.grounding,
                "broadened": t.broadened,
                "cache_hit": t.cache_hit,
                "channel": t.channel,
                "mode": t.mode,
                "model_key": t.model_key,
                "source_count": n,
                "cited_count": cited,
            }
            for t, n, cited in rows
        ],
    }


async def _current_texts(db: AsyncSession, sources: list[AnswerTraceSource], visible: set[str]) -> dict:
    """볼 수 있는 문서의 근거만 현재 본문을 읽는다. 표 행·캐시 인용은 원본 위치가 없어 읽지 않는다."""
    chunk_ids = {
        _as_uuid(s.chunk_ref) for s in sources
        if s.source_kind == "chunk" and s.document_id in visible and _as_uuid(s.chunk_ref)
    }
    summary_doc_ids = {
        s.document_id for s in sources if s.source_kind == "summary" and s.document_id in visible
    }
    chunk_texts: dict[str, str] = {}
    if chunk_ids:
        rows = await db.execute(
            select(DocumentChunk.id, DocumentChunk.document_id, DocumentChunk.chunk_text)
            .where(DocumentChunk.id.in_(chunk_ids))
        )
        # 청크가 기록된 문서에 실제로 속할 때만 본문을 쓴다(다른 문서 청크를 잘못 가리키는 경우 차단).
        chunk_texts = {f"{d}:{i}": text for i, d, text in rows.all()}
    summaries: dict[str, str] = {}
    if summary_doc_ids:
        rows = await db.execute(
            select(Document.id, Document.summary).where(Document.id.in_(summary_doc_ids))
        )
        summaries = {str(i): text for i, text in rows.all() if text}
    return {"chunk": chunk_texts, "summary": summaries}


def _source_view(source: AnswerTraceSource, existing: set[str], visible: set[str], texts: dict) -> dict:
    doc_id = source.document_id
    if doc_id in visible:
        access = ACCESS_VISIBLE
    elif doc_id in existing:
        access = ACCESS_HIDDEN
    else:
        access = ACCESS_DELETED

    if access != ACCESS_VISIBLE:
        # 볼 수 없는 문서는 파일명, 등급, 위치도 내려보내지 않는다. 파일명 자체가 민감할 수 있다.
        return {
            "rank": source.rank, "document_id": None, "collection_id": None, "filename": None,
            "security_level": None, "page_number": None, "source_kind": source.source_kind,
            "chunk_ref": None, "score": None, "cited": source.cited, "access": access,
            "text": None, "text_changed": None, "evidence": None,
        }

    text = None
    if source.source_kind == "chunk":
        text = texts["chunk"].get(f"{doc_id}:{_as_uuid(source.chunk_ref)}")
    elif source.source_kind == "summary":
        text = texts["summary"].get(doc_id)
    return {
        "rank": source.rank,
        "document_id": doc_id,
        "collection_id": source.collection_id,
        "filename": source.filename,
        "security_level": source.security_level,
        "page_number": source.page_number,
        "source_kind": source.source_kind,
        "chunk_ref": source.chunk_ref,
        "score": source.score,
        "evidence": source.evidence,
        "cited": source.cited,
        "access": access,
        "text": text,
        "text_changed": None if text is None else sha256_text(text) != source.text_sha256,
    }


@router.get("/admin/answer-traces/{trace_id}")
async def get_answer_trace(
    trace_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_admin(current_user)
    trace = await db.get(AnswerTrace, trace_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="Answer trace not found")

    sources = list(
        (
            await db.scalars(
                select(AnswerTraceSource)
                .where(AnswerTraceSource.trace_id == trace.id)
                .order_by(AnswerTraceSource.rank)
            )
        ).all()
    )
    from app.services.agentic.deep_search import mask_step_documents, step_document_ids

    doc_ids = ({_as_uuid(s.document_id) for s in sources} | step_document_ids(trace.agent_steps)) - {None}
    ctx = await build_access_context(db, current_user)
    facts = await load_document_facts(db, doc_ids) if doc_ids else {}
    visible = visible_document_ids(ctx, facts)
    texts = await _current_texts(db, sources, visible)

    log_audit(
        db, str(current_user.id), "answer_trace.view", "answer_trace", str(trace.id),
        detail={"hidden_sources": sum(1 for s in sources if s.document_id not in visible)},
    )
    await db.commit()

    return {
        "id": str(trace.id),
        "created_at": trace.created_at,
        "chat_message_id": str(trace.chat_message_id) if trace.chat_message_id else None,
        "conversation_id": str(trace.conversation_id) if trace.conversation_id else None,
        "user_id": str(trace.user_id) if trace.user_id else None,
        "username": trace.username,
        "user_role": trace.user_role,
        "clearance_level": trace.clearance_level,
        "group_ids": trace.group_ids or [],
        "accessible_collection_count": trace.accessible_collection_count,
        "access_fingerprint": trace.access_fingerprint,
        "scope_collection_id": str(trace.scope_collection_id) if trace.scope_collection_id else None,
        "scope_project_id": str(trace.scope_project_id) if trace.scope_project_id else None,
        "intent": trace.intent,
        "broadened": trace.broadened,
        "grounding": trace.grounding,
        "cache_hit": trace.cache_hit,
        "channel": trace.channel,
        "access_token_id": str(trace.access_token_id) if trace.access_token_id else None,
        "mode": trace.mode,
        # 하위 질문별 검색 과정. 관리자가 지금 볼 수 없는 문서는 근거 발췌문처럼 가린다
        "agent_steps": mask_step_documents(trace.agent_steps, visible),
        "model_key": trace.model_key,
        "provider": trace.provider,
        "verifier_model": trace.verifier_model,
        "system_prompt_source": trace.system_prompt_source,
        "system_prompt_sha256": trace.system_prompt_sha256,
        "input_tokens": trace.input_tokens,
        "output_tokens": trace.output_tokens,
        "latency_ms": trace.latency_ms,
        "query": trace.query,
        "answer": trace.answer,
        "status": trace.status,
        "error_message": trace.error_message,
        "sources": [_source_view(s, set(facts), visible, texts) for s in sources],
    }
