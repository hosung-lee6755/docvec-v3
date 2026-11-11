"""답변 추적 기록 작성(채팅 워커, sync 세션).

`record_answer_trace`는 답변 상태를 저장하는 커밋과 같은 트랜잭션에 기록을 더한다.
SAVEPOINT 안에서 쓰므로 기록이 실패해도 답변 저장은 그대로 진행되고, 예외는 로그로만 남는다
(`log_audit`과 같은 원칙). 청크 본문은 저장하지 않고 SHA-256 해시만 남긴다.
"""
from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Iterable, Sequence
from uuid import UUID

from app.db.models.answer_trace import AnswerTrace, AnswerTraceSource
from app.services.access_policy import (
    DEFAULT_DOCUMENT_LEVEL,
    SECURITY_LEVELS,
    AccessContext,
    load_document_facts_sync,
)

logger = logging.getLogger(__name__)

_CITATION_RE = re.compile(r"\[(\d+)\]")
_ERROR_MAX_LEN = 500


def sha256_text(text: str | None) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def cited_ranks(answer: str | None) -> set[int]:
    """답변 본문에 [n] 형식으로 실제 인용된 발췌문 번호."""
    return {int(n) for n in _CITATION_RE.findall(answer or "")}


def _valid_uuids(values: Iterable[str | None]) -> set[str]:
    out = set()
    for value in values:
        try:
            out.add(str(UUID(str(value))))
        except (TypeError, ValueError):
            continue
    return out


def _effective_levels(db, document_ids: Iterable[str | None]) -> dict[str, str]:
    """기록 시점의 문서 유효 등급(문서 → 컬렉션 기본값 → Public)."""
    ids = _valid_uuids(document_ids)
    if not ids:
        return {}
    facts = load_document_facts_sync(db, ids)
    return {
        doc_id: f.security_level or f.collection_default_level or DEFAULT_DOCUMENT_LEVEL
        for doc_id, f in facts.items()
    }


def _clearance_level(ctx: AccessContext | None) -> str | None:
    if ctx is None:
        return None
    return SECURITY_LEVELS[ctx.clearance_rank]


def build_sources(
    chunks: Sequence[dict], answer: str | None, levels: dict[str, str], default_kind: str
) -> list[AnswerTraceSource]:
    cited = cited_ranks(answer)
    return [
        AnswerTraceSource(
            rank=rank,
            document_id=chunk.get("document_id"),
            collection_id=chunk.get("collection_id"),
            filename=chunk.get("filename"),
            security_level=levels.get(str(chunk.get("document_id"))),
            page_number=chunk.get("page_number"),
            source_kind=chunk.get("source_kind") or default_kind,
            chunk_ref=chunk.get("chunk_ref"),
            score=chunk.get("score"),
            text_sha256=sha256_text(chunk.get("text")),
            cited=rank in cited,
        )
        for rank, chunk in enumerate(chunks, start=1)
    ]


def record_answer_trace(
    db,
    *,
    query: str,
    status: str,
    chunks: Sequence[dict] = (),
    answer: str | None = None,
    error_message: str | None = None,
    chat_message_id: str | None = None,
    conversation_id: str | None = None,
    user=None,
    access_ctx: AccessContext | None = None,
    scope_collection_id: str | None = None,
    scope_project_id: str | None = None,
    intent: str | None = None,
    broadened: bool = False,
    grounding: str | None = None,
    cache_hit: bool = False,
    model_key: str | None = None,
    provider: str | None = None,
    verifier_model: str | None = None,
    system_prompt_source: str | None = None,
    system_prompt: str | None = None,
    usage: dict | None = None,
    latency_ms: int | None = None,
    channel: str = "web",
    access_token_id: str | None = None,
) -> None:
    """답변 한 건의 추적 기록을 세션에 더한다. 커밋은 호출자가 한다. 예외를 던지지 않는다."""
    try:
        with db.begin_nested():
            trace = AnswerTrace(
                chat_message_id=chat_message_id,
                conversation_id=conversation_id,
                user_id=str(user.id) if user is not None else None,
                username=getattr(user, "username", None),
                user_role=getattr(user, "role", None),
                clearance_level=_clearance_level(access_ctx),
                group_ids=sorted(access_ctx.group_ids) if access_ctx else None,
                accessible_collection_count=len(access_ctx.collection_ids) if access_ctx else 0,
                access_fingerprint=access_ctx.fingerprint() if access_ctx else None,
                scope_collection_id=scope_collection_id,
                scope_project_id=scope_project_id,
                intent=intent,
                broadened=broadened,
                grounding=grounding,
                cache_hit=cache_hit,
                model_key=model_key,
                provider=provider,
                verifier_model=verifier_model,
                system_prompt_source=system_prompt_source,
                system_prompt_sha256=sha256_text(system_prompt) if system_prompt else None,
                input_tokens=(usage or {}).get("input_tokens"),
                output_tokens=(usage or {}).get("output_tokens"),
                latency_ms=latency_ms,
                channel=channel,
                access_token_id=access_token_id,
                query=query,
                answer=answer,
                status=status,
                error_message=(error_message or "")[:_ERROR_MAX_LEN] or None,
            )
            db.add(trace)
            db.flush()
            levels = _effective_levels(db, (c.get("document_id") for c in chunks))
            default_kind = "cached" if cache_hit else "chunk"
            for source in build_sources(chunks, answer, levels, default_kind):
                source.trace_id = trace.id
                db.add(source)
            db.flush()
    except Exception:
        logger.exception(
            "answer trace recording failed", extra={"chat_message_id": chat_message_id}
        )
