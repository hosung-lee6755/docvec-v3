import hashlib
import json
import logging
import re
import time

from app.core.config import settings
from app.pipeline.celery_app import celery_app
from app.services.retrieval_evidence import matched_terms, ocr_evidence, page_confidences_sync, score_evidence

logger = logging.getLogger(__name__)

# Exact-match answer cache TTL. Not a semantic/similarity cache — only identical
# (query, scope, model) hits reuse a cached answer. Bounds staleness after a
# document is reprocessed without needing explicit cache invalidation.
_ANSWER_CACHE_TTL_SECONDS = 3600


def _answer_cache_key(
    query: str,
    collection_id: str | None,
    project_id: str | None,
    model_key: str,
    access_fingerprint: str,
    mode: str = "standard",
    variant: str = "",
) -> str:
    """access_fingerprint(AccessContext.fingerprint)를 반드시 포함한다 — 빠지면 높은
    등급 사용자가 받은 답변(과 인용)이 같은 질문을 한 낮은 등급 사용자에게 캐시로
    나간다(v3 권한 모델의 누출 경로). 같은 권한 조합끼리만 캐시를 공유한다."""
    normalized = query.strip().lower()
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    # 심층 검색은 같은 질문이라도 근거와 답이 달라 캐시를 따로 둔다. 일반 답변의 키는 그대로다
    prefix = "rag_answer" if mode == "standard" else f"rag_answer_{mode}"
    key = (
        f"{prefix}:{model_key}:{collection_id or 'all'}:{project_id or 'none'}:"
        f"{access_fingerprint}:{digest}"
    )
    # variant: 검색 결과를 바꾸는 설정(컬렉션 검색 설정, 사전 리비전). 바뀌면 예전 답을 다시 쓰지 않는다
    return f"{key}:{variant}" if variant else key


def _retrieval_variant(db, collection_id: str | None) -> str:
    """답변 캐시 키에 넣을 검색 조건 요약. 설정이나 사전이 바뀌면 값이 달라진다."""
    from app.services import dictionary_service
    from app.services.search_settings import collection_search_settings_sync

    search = collection_search_settings_sync(db, collection_id)
    settings_digest = hashlib.sha256(search.model_dump_json().encode("utf-8")).hexdigest()[:12]
    try:
        dictionary_service.ensure_dictionary_cache_sync(db)
    except Exception:  # noqa: BLE001 - 사전을 못 읽어도 답은 만들고, 캐시만 리비전 없이 나눈다
        logger.exception("dictionary cache reload failed")
    return f"s{settings_digest}:d{dictionary_service._loaded_revision}"

_SYSTEM_PROMPT = (
    "당신은 문서 검색 결과를 바탕으로 답변하는 어시스턴트입니다. "
    "아래 제공된 발췌문만 근거로, 완전한 문장으로 이루어진 설명을 작성하세요. "
    "각 문장이나 문단 끝에는 그 내용의 근거가 된 발췌문 번호를 [1], [2] 형식으로 표시하세요. "
    "절대로 인용 번호만 단독으로 출력하지 말고, 항상 문장 설명과 함께 표시하세요. "
    "예시: \"소상공인 매출은 최근 3년간 증가하는 추세입니다[1]. 특히 20대 창업 비율이 높습니다[2].\" "
    "발췌문에서 답을 찾을 수 없으면 그 이유를 문장으로 설명하며 모른다고 답하세요. "
    "반드시 한국어(한글)로만 답변하세요. 중국어(한자)로 답변하는 것은 금지됩니다."
)

# A response made of nothing but bracketed citation markers (e.g. "[1], [4]") means
# the local model terminated right after echoing the citation format instead of
# actually answering — retry once with a stronger nudge before giving up.
_BARE_CITATION_RE = re.compile(r"^[\[\]0-9,.\s]+$")


def _is_degenerate_answer(answer: str) -> bool:
    stripped = answer.strip()
    return bool(stripped) and bool(_BARE_CITATION_RE.match(stripped))


_REFLECTION_SYSTEM_PROMPT = (
    "당신은 답변이 주어진 발췌문에 충분히 근거하는지 평가하는 검증자입니다. "
    "답변이 발췌문 내용만으로 충분히 뒷받침되면 'SUFFICIENT', "
    "발췌문에 없는 내용을 추측했거나 근거가 부족하면 'INSUFFICIENT'라고만 답하세요."
)

# Routes a chat query to one of three retrieval strategies before generation.
# Kept as a single-label LLM classification (not a heuristic/keyword match) so
# it generalizes across phrasings; falls back to the default chunk search on
# any ambiguity or classifier failure rather than risking a wrong-shaped
# retrieval for an unclear question.
_INTENT_SYSTEM_PROMPT = (
    "당신은 사용자 질문을 세 가지 카테고리 중 하나로 분류하는 라우터입니다. "
    "다음 중 정확히 하나의 라벨만 출력하세요: CHUNK_SEARCH, TABLE_QUERY, SUMMARY_LOOKUP. "
    "TABLE_QUERY: 질문이 표/통계/수치 데이터, 특정 항목의 수치 비교, 표 형식 자료를 요구하는 경우. "
    "SUMMARY_LOOKUP: 질문이 문서 전체의 요약, 개요, 핵심 내용을 요청하는 경우 "
    "(예: '이 문서 요약해줘', '주요 내용이 뭐야', '전체적으로 어떤 내용이야'). "
    "CHUNK_SEARCH: 그 외 일반적인 사실 확인, 특정 내용/문장 검색인 경우. "
    "라벨 외의 다른 텍스트는 절대 출력하지 마세요."
)


def _classify_intent(provider, query: str) -> str:
    try:
        verdict = provider.generate(
            _INTENT_SYSTEM_PROMPT,
            [{"role": "user", "content": f"질문: {query}\n\n라벨:"}],
        )
        upper = verdict.strip().upper()
        if "TABLE_QUERY" in upper:
            return "table_query"
        if "SUMMARY_LOOKUP" in upper:
            return "summary_lookup"
        return "chunk_search"
    except Exception:
        logger.exception("chat intent classification failed; defaulting to chunk_search")
        return "chunk_search"


def _find_api_key(db, conversation, backend: str) -> str | None:
    """A project-scoped BYOK key takes priority over the requester's personal
    key, matching the priority order used when resolving the key for
    generation itself."""
    from app.core.crypto import decrypt_secret
    from app.db.models.project_api_key import ProjectApiKey
    from app.db.models.user_api_key import UserApiKey

    key_row = None
    if conversation.project_id:
        key_row = (
            db.query(ProjectApiKey)
            .filter_by(project_id=conversation.project_id, provider=backend)
            .first()
        )
    if not key_row:
        key_row = (
            db.query(UserApiKey)
            .filter_by(user_id=conversation.user_id, provider=backend)
            .first()
        )
    return decrypt_secret(key_row.encrypted_key) if key_row else None


# Preferred (backend, model_key) pairs for the self-reflection verification
# hop specifically — cheap/fast cloud models, tried in order. Generation stays
# on whatever model_key the conversation picked (often local); only the
# grounding check is delegated to the cloud when a BYOK key makes it available.
_VERIFICATION_MODEL_PRIORITY = [("openai", "gpt-4o-mini"), ("anthropic", "claude-3-5-haiku")]


def _get_verifier_provider(db, conversation, generation_provider, generation_backend: str):
    if generation_backend in ("openai", "anthropic"):
        # Generation is already on a cloud model — reuse it rather than paying
        # for a second provider instantiation and a second BYOK key lookup.
        return generation_provider
    for backend, model_key in _VERIFICATION_MODEL_PRIORITY:
        key = _find_api_key(db, conversation, backend)
        if not key:
            continue
        try:
            from app.services.llm import get_llm_provider

            return get_llm_provider(model_key, api_key=key)
        except Exception:
            logger.exception("generate_answer: failed to init cloud verifier %s", model_key)
    return generation_provider


def _is_answer_grounded(provider, query: str, context: str, answer: str) -> bool:
    verdict = provider.generate(
        _REFLECTION_SYSTEM_PROMPT,
        [{
            "role": "user",
            "content": f"질문: {query}\n\n발췌문:\n{context}\n\n답변: {answer}\n\n평가:",
        }],
    )
    return "INSUFFICIENT" not in verdict.strip().upper()


def _build_context(chunks: list[dict]) -> str:
    citation_lines = []
    for i, c in enumerate(chunks, start=1):
        page_part = f" ({c['page_number']}쪽)" if c.get("page_number") else ""
        citation_lines.append(f"[{i}] {c['filename']}{page_part}: {c['text']}")
    return "\n\n".join(citation_lines) or "(관련 발췌문 없음)"

# Number of prior Q&A pairs from the same conversation included as chat history —
# capped to bound prompt length/latency for local (CPU/GPU-bound) inference.
_MAX_HISTORY_TURNS = 3
_PROGRESS_TTL_SECONDS = 600


def _progress_writer(redis_client, chat_message_id: str):
    """심층 검색 진행 단계를 Redis에 적는 함수. 채팅 화면이 메시지를 읽을 때 함께 내려준다."""
    key = f"chat_progress:{chat_message_id}"

    def write(state: dict) -> None:
        try:
            redis_client.setex(key, _PROGRESS_TTL_SECONDS, json.dumps(state, ensure_ascii=False))
        except Exception:
            logger.warning("generate_answer: failed to write deep search progress", exc_info=True)

    return write

# Over-fetch this many times the requested limit before BM25 reranking, mirroring
# search_service.py::perform_search's hybrid-search candidate pool.
_HYBRID_CANDIDATE_MULTIPLIER = 4
# 검색 화면(search_service._MMR_LAMBDA)과 같은 관련도 대 다양성 비중
_MMR_LAMBDA = 0.7
# 근거 확인에 실패해 넓혀 다시 찾을 때의 근거 수
_BROADEN_LIMIT = 10


def _accessible_collection_ids(db, user_id: str, project_id: str | None = None) -> list[str]:
    """API의 permissions.accessible_collection_ids와 같은 문(access_policy)을 sync 세션으로
    실행한다 — 규칙을 여기서 따로 구현하지 않는다(v2에서는 두 벌이라 어긋날 위험이 있었다)."""
    from app.services.access_policy import accessible_collection_ids_stmt

    stmt = accessible_collection_ids_stmt(str(user_id), str(project_id) if project_id else None)
    return list({str(cid) for cid in db.scalars(stmt).all()})


def _cited_documents_still_visible(db, access_ctx, cached_payload: dict) -> bool:
    """캐시 키의 권한 지문은 사용자 쪽(열람등급·그룹·컬렉션)만 담는다. 문서 쪽 권한(등급·ACL)이
    캐시 이후 바뀌면 같은 키로 낡은 답변·인용이 나가므로, 적중할 때마다 인용 문서를 Postgres로
    다시 판정한다. 심층 검색 답변이면 검색 과정에 적힌 문서(인용되지 않은 검색 결과 포함)도 함께
    판정한다. 하나라도 지금 볼 수 없거나 더는 현재 버전이 아니면(새 버전, 보관, 만료) 캐시를
    버리고 새로 만든다."""
    from app.services.access_policy import load_document_facts_sync, retrievable_document_ids
    from app.services.agentic.deep_search import step_document_ids

    doc_ids = {c.get("document_id") for c in cached_payload.get("citations") or []}
    doc_ids |= step_document_ids(cached_payload.get("agent_steps"))
    doc_ids.discard(None)
    if not doc_ids:
        return True
    facts = load_document_facts_sync(db, doc_ids)
    return doc_ids <= retrievable_document_ids(access_ctx, facts)


def _scope_collection_ids(
    db, user_id: str, collection_id: str | None, project_id: str | None
) -> list[str]:
    """이번 질의의 컬렉션 범위. 단일 컬렉션은 대화 생성 시 접근 확인을 마쳤다(endpoints/chat.py).
    범위 없이 검색하면 물리 Qdrant 컬렉션을 공유하는 다른 사용자의 문서가 나오므로 반드시 좁힌다."""
    if collection_id:
        return [str(collection_id)]
    return _accessible_collection_ids(db, user_id, project_id=project_id)


def _retrieve_chunks(
    db,
    user_id: str,
    query: str,
    collection_id: str | None,
    project_id: str | None = None,
    limit: int | None = None,
    record_stats: bool = True,
) -> list[dict]:
    """권한 범위 안에서 질문에 맞는 청크를 찾는다. 범위가 컬렉션 하나면 그 컬렉션의 검색 설정
    (방식, 근거 수, MMR, 재순위, 벡터 비중)을 따른다(v3 마일스톤 6). limit을 넘기면 근거 수만 바꾼다.
    record_stats=False는 골든 평가처럼 사용자 질의가 아닌 검색에서 청크 조회 통계를 남기지 않는다."""
    from app.db.models.collection import Collection
    from app.services.bm25_service import bm25_rerank
    from app.services.dictionary_service import ensure_dictionary_cache_sync, expand_query
    from app.services.embedding import get_embedding_provider
    from app.services.qdrant_service import qdrant_service
    from app.services.search_settings import collection_search_settings_sync

    from app.services.access_policy import (
        build_access_context_sync,
        load_document_facts_sync,
        qdrant_access_filter,
        retrievable_document_ids,
    )

    scope = _scope_collection_ids(db, user_id, collection_id, project_id)
    if not scope:
        return []

    # v3 권한: 검색 단계에서 보안등급·ACL로 거르고, 리랭킹·LLM에 넣기 전에 Postgres
    # 기준으로 다시 확인한다(페이로드 동기화가 늦어도 근거·인용으로 새지 않게 — fail-closed).
    ctx = build_access_context_sync(db, user_id)
    search = collection_search_settings_sync(db, collection_id)
    limit = limit or search.top_k
    # 사전의 검색어 확장(SEARCH_EXPAND)을 검색 화면과 똑같이 쓴다. 재순위는 원래 질문으로 판단한다.
    # 사전을 읽지 못해도 검색은 원래 질문으로 계속한다(마일스톤 6 이전에는 사전 없이 찾았다)
    try:
        ensure_dictionary_cache_sync(db)
        search_query, _added = expand_query(query)
    except Exception:  # noqa: BLE001
        logger.exception("query expansion failed; searching with the original query")
        search_query = query
    provider = get_embedding_provider()
    vector = provider.embed([search_query])[0]
    hits = qdrant_service.search(
        collection=settings.qdrant_collection_name,
        vector=vector,
        limit=limit * _HYBRID_CANDIDATE_MULTIPLIER,
        with_vectors=search.diversify,
        query_filter=qdrant_access_filter(ctx, scope),
    )
    if hits:
        facts = load_document_facts_sync(db, {h["payload"].get("document_id") for h in hits})
        allowed = retrievable_document_ids(ctx, facts)
        hits = [h for h in hits if h["payload"].get("document_id") in allowed]

    if hits:
        from app.services.chunk_stats import record_hits
        from app.services.reranker import cross_encoder_rerank

        candidates = [
            {
                "id": h["id"],
                "text": h["payload"].get("text", ""),
                # Contextual BM25 — falls back to plain text for points indexed
                # before this field existed (see rag_store's storage_blocks.py).
                "bm25_text": h["payload"].get("index_text") or h["payload"].get("text", ""),
                "score": h["score"],
                "vector": h.get("vector"),
                "payload": h["payload"],
            }
            for h in hits
        ]
        ranked = _rank_candidates(query, search_query, candidates, search, limit, bm25_rerank, cross_encoder_rerank)
        hits = [
            {
                "id": c["id"],
                "score": c.get("rerank_score", c.get("final_score", c["score"])),
                "payload": c["payload"],
                "evidence": {"scores": score_evidence(c)},
            }
            for c in ranked
        ]
        if record_stats:
            record_hits([h["id"] for h in hits])
        _attach_evidence(db, search_query, hits)

    hit_collection_ids = {h["payload"].get("collection_id") for h in hits}
    hit_collection_ids.discard(None)
    collection_names: dict[str, str] = {}
    if hit_collection_ids:
        rows = db.query(Collection.id, Collection.name).filter(
            Collection.id.in_(hit_collection_ids)
        ).all()
        collection_names = {str(row[0]): row[1] for row in rows}

    return [
        {
            "document_id": h["payload"].get("document_id"),
            "collection_id": h["payload"].get("collection_id"),
            "collection_name": collection_names.get(h["payload"].get("collection_id")),
            "filename": h["payload"].get("filename"),
            "page_number": h["payload"].get("page_number"),
            "text": h["payload"].get("text", ""),
            "source_kind": "chunk",
            "chunk_ref": str(h["id"]),
            "score": h["score"],
            "evidence": h.get("evidence"),
        }
        for h in hits
    ]


def _rank_candidates(query, search_query, candidates, search, limit, bm25_rerank, cross_encoder_rerank) -> list[dict]:
    """1단계(재현율): 하이브리드면 벡터와 BM25 점수를 섞고, 벡터 방식이면 벡터 점수 순서다.
    MMR을 켜면 비슷한 발췌문을 덜 뽑는다. 2단계(정밀도): 재순위를 켜면 교차 인코더가 (질문, 본문)을
    함께 읽어 최종 근거를 고른다. 모델이 없으면 1단계 순서를 쓴다. 재순위는 맥락을 붙인 bm25_text가
    아니라 실제 본문(text)을 원래 질문과 비교한다."""
    from app.services.mmr_service import mmr_rerank

    if search.mode == "hybrid":
        weight = search.vector_weight
        ranked = bm25_rerank(search_query, candidates, text_field="bm25_text",
                             alpha_vector=weight, alpha_bm25=round(1 - weight, 4))
        relevance = "final_score"
    else:
        ranked = sorted(candidates, key=lambda c: c["score"], reverse=True)
        relevance = "score"
    pool_size = limit * 2 if search.rerank else limit
    if search.diversify and all(c.get("vector") for c in ranked):
        pool = mmr_rerank(ranked, k=pool_size, relevance_field=relevance, lambda_param=_MMR_LAMBDA)
    else:
        pool = ranked[:pool_size]
    if search.rerank:
        return cross_encoder_rerank(query, pool, text_field="text", top_k=limit)
    return pool[:limit]


def _attach_evidence(db, search_query: str, hits: list[dict]) -> None:
    """근거마다 질문과 겹친 낱말과 그 쪽의 OCR 신뢰도를 덧붙인다(v3 마일스톤 6)."""
    terms = matched_terms(search_query, [h["payload"].get("text", "") for h in hits])
    confidences = page_confidences_sync(db, {h["payload"].get("document_id") for h in hits})
    for h, matched in zip(hits, terms):
        h["evidence"].update(
            {"matched_terms": matched,
             **ocr_evidence(confidences, h["payload"].get("document_id"), h["payload"].get("page_number"))}
        )


def _accessible_documents(db, user_id: str, collection_id: str | None, project_id: str | None = None) -> list:
    """Same collection-scoping rule as _retrieve_chunks/_accessible_collection_ids,
    but returns Document rows instead of Qdrant hits — used by the table/summary
    retrieval paths, which read structured fields on Document rather than
    embedded chunk text."""
    from app.db.models.document import Document
    from app.services.access_policy import (
        build_access_context_sync,
        document_retrievable_clause,
        document_visibility_clause,
    )

    collection_ids = _scope_collection_ids(db, user_id, collection_id, project_id)
    if not collection_ids:
        return []

    ctx = build_access_context_sync(db, user_id)
    return (
        db.query(Document)
        .filter(
            Document.collection_id.in_(collection_ids),
            Document.status == "INDEXED",
            document_visibility_clause(ctx),
            # 표와 요약도 현재 버전에서만 찾는다(v3 마일스톤 7)
            document_retrievable_clause(),
        )
        .all()
    )


def _attach_collection_names(db, candidates: list[dict]) -> list[dict]:
    from app.db.models.collection import Collection

    ids = {c.get("collection_id") for c in candidates}
    ids.discard(None)
    names: dict[str, str] = {}
    if ids:
        rows = db.query(Collection.id, Collection.name).filter(Collection.id.in_(ids)).all()
        names = {str(row[0]): row[1] for row in rows}
    return [{**c, "collection_name": names.get(c.get("collection_id"))} for c in candidates]


def _retrieve_table_chunks(
    db,
    user_id: str,
    query: str,
    collection_id: str | None,
    project_id: str | None = None,
    limit: int = 5,
) -> list[dict]:
    """표 데이터 질의 intent: search structured table rows (Document.tables) instead
    of embedded text chunks. There is no vector index over tables, so ranking is
    BM25-only (bm25_rerank falls back to keyword score when "score" is absent)."""
    from app.services.bm25_service import bm25_rerank

    docs = _accessible_documents(db, user_id, collection_id, project_id=project_id)
    candidates = []
    for doc in docs:
        for table in doc.tables or []:
            rows = table.get("rows") or []
            if not rows:
                continue
            text = "\n".join(" | ".join(str(cell) for cell in row) for row in rows)
            candidates.append({
                "document_id": str(doc.id),
                "collection_id": str(doc.collection_id) if doc.collection_id else None,
                "filename": doc.original_filename,
                "page_number": table.get("page_number"),
                "text": text,
                "source_kind": "table",
            })

    if not candidates:
        return []

    ranked = bm25_rerank(query, candidates, text_field="text")[:limit]
    return _attach_collection_names(db, ranked)


def _retrieve_summary_chunks(
    db,
    user_id: str,
    query: str,
    collection_id: str | None,
    project_id: str | None = None,
    limit: int = 5,
) -> list[dict]:
    """요약 조회 intent: answer from each accessible document's stored summary
    (Document.summary) instead of retrieving individual chunks — appropriate when
    the user is asking for an overview rather than a specific fact/passage."""
    from app.services.bm25_service import bm25_rerank

    docs = _accessible_documents(db, user_id, collection_id, project_id=project_id)
    candidates = [
        {
            "document_id": str(doc.id),
            "collection_id": str(doc.collection_id) if doc.collection_id else None,
            "filename": doc.original_filename,
            "page_number": None,
            "text": doc.summary,
            "source_kind": "summary",
        }
        for doc in docs
        if doc.summary_status == "DONE" and doc.summary
    ]

    if not candidates:
        return []

    # A handful of documents in scope: their summaries are short enough to all be
    # relevant context rather than something to rank away, unlike table rows/chunks
    # which can number in the hundreds. Still cap at limit for prompt-size safety.
    if len(candidates) <= limit:
        return _attach_collection_names(db, candidates)

    ranked = bm25_rerank(query, candidates, text_field="text")[:limit]
    return _attach_collection_names(db, ranked)


def _select_system_prompt(project, requester) -> tuple[str, str]:
    """(출처, 프롬프트). 프로젝트 → 사용자 → 기본 순으로 고른다. 출처는 답변 추적 기록에 남는다."""
    if project is not None and project.system_prompt:
        return "project", project.system_prompt
    if requester is not None and requester.system_prompt:
        return "user", requester.system_prompt
    return "default", _SYSTEM_PROMPT


def _verifier_model_key(verifier, generation_provider, generation_model_key: str) -> str | None:
    if verifier is generation_provider:
        return generation_model_key
    return getattr(verifier, "_model", None)


def _expanded_terms(db, query: str) -> list[str] | None:
    """사전의 검색어 확장으로 질문에 덧붙인 낱말. 화면에 보여 주려고 메시지에 남긴다."""
    from app.services.dictionary_service import ensure_dictionary_cache_sync, expand_query

    try:
        ensure_dictionary_cache_sync(db)
        return expand_query(query)[1] or None
    except Exception:
        logger.warning("generate_answer: query expansion lookup failed", exc_info=True)
        return None


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


@celery_app.task(name="tasks.generate_answer", queue="high", bind=True, max_retries=2)
def generate_answer(self, chat_message_id: str) -> dict:
    from app.db.models.answer_trace import (
        GROUNDING_FAILED,
        GROUNDING_PASSED,
        GROUNDING_SKIPPED,
    )
    from app.db.models.chat_conversation import ChatConversation
    from app.db.models.chat_message import ChatMessage
    from app.db.models.project import Project
    from app.db.models.user import User
    from app.db.session import get_sync_db
    from app.services.answer_trace import record_answer_trace
    from app.services.llm import LLM_MODEL_REGISTRY, get_llm_provider

    started = time.monotonic()
    db = get_sync_db()
    # 답변 추적 기록(v3 마일스톤 2)에 넣을 사실을 단계마다 모은다. 실패 경로에서도
    # 그때까지 알게 된 사실로 기록을 남기기 위해서다.
    trace: dict = {}
    try:
        msg = db.get(ChatMessage, chat_message_id)
        if msg is None:
            return {"chat_message_id": chat_message_id, "status": "NOT_FOUND"}

        conversation = db.get(ChatConversation, msg.conversation_id)
        if conversation is None:
            raise ValueError(f"Conversation not found: {msg.conversation_id}")

        msg.status = "GENERATING"
        db.commit()

        import redis

        from app.services.access_policy import build_access_context_sync

        collection_id_str = str(conversation.collection_id) if conversation.collection_id else None
        project_id_str = str(conversation.project_id) if conversation.project_id else None
        requester = db.get(User, conversation.user_id)
        trace.update(
            query=msg.query,
            chat_message_id=chat_message_id,
            conversation_id=str(conversation.id),
            user=requester,
            scope_collection_id=collection_id_str,
            scope_project_id=project_id_str,
            model_key=conversation.model_key,
            channel=conversation.channel or "web",
            access_token_id=str(conversation.access_token_id) if conversation.access_token_id else None,
            mode=msg.mode or "standard",
        )
        is_deep = trace["mode"] == "deep"

        redis_client = redis.from_url(settings.redis_url)
        access_ctx = build_access_context_sync(db, str(conversation.user_id))
        trace["access_ctx"] = access_ctx
        cache_key = _answer_cache_key(
            msg.query,
            collection_id_str,
            project_id_str,
            conversation.model_key,
            access_ctx.fingerprint(),
            mode=trace["mode"],
            variant=_retrieval_variant(db, collection_id_str),
        )
        cached = redis_client.get(cache_key)
        cached_payload = json.loads(cached) if cached else None
        if cached_payload and not _cited_documents_still_visible(db, access_ctx, cached_payload):
            # 캐시 이후 인용 문서의 등급·ACL이 바뀌었다 — 낡은 답변을 버리고 새로 만든다.
            redis_client.delete(cache_key)
            cached_payload = None
        if cached_payload:
            msg.answer = cached_payload["answer"]
            msg.citations = cached_payload["citations"]
            msg.agent_steps = cached_payload.get("agent_steps")
            msg.expanded_terms = cached_payload.get("expanded_terms")
            trace["agent_steps"] = msg.agent_steps
            msg.status = "DONE"
            record_answer_trace(
                db, **trace, status="DONE", answer=msg.answer, chunks=msg.citations or [],
                cache_hit=True, latency_ms=_elapsed_ms(started),
            )
            db.commit()
            return {"chat_message_id": chat_message_id, "status": "DONE", "cached": True}

        spec = LLM_MODEL_REGISTRY.get(conversation.model_key)
        if spec is None:
            raise ValueError(f"Unknown model: {conversation.model_key}")
        trace["provider"] = spec["backend"]

        api_key = None
        if spec["backend"] in ("openai", "anthropic"):
            api_key = _find_api_key(db, conversation, spec["backend"])
            if not api_key:
                raise ValueError(f"{spec['backend']} API 키가 등록되어 있지 않습니다")

        provider = get_llm_provider(conversation.model_key, api_key=api_key)

        # Route to one of three retrieval strategies based on what the query is
        # actually asking for — see _classify_intent's docstring/prompt for the
        # 3-way split (문서 검색 / 표 데이터 질의 / 요약 조회).
        subquestions: list[str] = [msg.query]
        agent_steps: dict | None = None
        progress = _progress_writer(redis_client, chat_message_id)
        if is_deep:
            # 심층 검색(v3 마일스톤 5): 의도 분류 대신 질문을 나눠 하위 질문마다 찾는다.
            # 모든 검색은 권한 필터가 걸린 _retrieve_chunks를 지난다.
            from app.services.agentic.deep_search import run_deep_search

            trace["intent"] = "deep"
            retrieval_fn = _retrieve_chunks
            deep = run_deep_search(
                provider, msg.query,
                lambda q, limit: _retrieve_chunks(
                    db, str(conversation.user_id), q, collection_id_str, project_id=project_id_str, limit=limit,
                ),
                progress,
            )
            chunks, subquestions, agent_steps = deep.chunks, deep.subquestions, dict(deep.steps)
            # 종합이나 확인 단계에서 실패해도 어디까지 찾았는지 추적에 남도록 바로 붙인다
            trace["agent_steps"] = agent_steps
            progress({"phase": "answering", "subquestions": subquestions})
        else:
            intent = _classify_intent(provider, msg.query)
            trace["intent"] = intent
            retrieval_fn = {
                "table_query": _retrieve_table_chunks,
                "summary_lookup": _retrieve_summary_chunks,
            }.get(intent, _retrieve_chunks)

            chunks = retrieval_fn(
                db, str(conversation.user_id), msg.query, collection_id_str, project_id=project_id_str
            )
            if not chunks and retrieval_fn is not _retrieve_chunks:
                # 요약이나 표가 없는 문서에서 근거 0건으로 답을 지어내지 않도록 일반 검색으로 다시 찾는다.
                # 분류기가 사실 질문을 요약 조회로 잘못 고를 때도 이 길로 구제된다.
                logger.info(
                    "generate_answer: intent retrieval found nothing, falling back to chunk search",
                    extra={"chat_message_id": chat_message_id, "intent": intent},
                )
                retrieval_fn = _retrieve_chunks
                chunks = retrieval_fn(
                    db, str(conversation.user_id), msg.query, collection_id_str, project_id=project_id_str
                )
        msg.expanded_terms = _expanded_terms(db, msg.query)
        answer_started = time.monotonic()
        context = _build_context(chunks)

        prior_messages = (
            db.query(ChatMessage)
            .filter(
                ChatMessage.conversation_id == conversation.id,
                ChatMessage.id != msg.id,
                ChatMessage.status == "DONE",
            )
            .order_by(ChatMessage.created_at)
            .all()
        )[-_MAX_HISTORY_TURNS:]

        history_messages: list[dict[str, str]] = []
        for h in prior_messages:
            history_messages.append({"role": "user", "content": h.query})
            history_messages.append({"role": "assistant", "content": h.answer or ""})

        project = db.get(Project, conversation.project_id) if conversation.project_id else None
        prompt_source, system_prompt = _select_system_prompt(project, requester)
        trace.update(system_prompt_source=prompt_source, system_prompt=system_prompt)

        # Polling-based streaming: the worker mirrors partial output into Redis
        # and the message API surfaces it while status is GENERATING, so the
        # 1.5s frontend poll renders text as it's produced instead of waiting
        # for the full answer.
        partial_key = f"chat_partial:{chat_message_id}"

        def _write_partial(text_so_far: str) -> None:
            try:
                redis_client.setex(partial_key, 300, text_so_far)
            except Exception:
                pass

        def _user_content(ctx: str) -> str:
            if is_deep:
                from app.services.agentic.deep_search import synthesis_message

                return synthesis_message(msg.query, subquestions, ctx)
            return f"질문: {msg.query}\n\n발췌문:\n{ctx}"

        def _generate(ctx: str) -> str:
            messages = [*history_messages, {"role": "user", "content": _user_content(ctx)}]
            result = provider.generate_stream(system_prompt, messages, _write_partial)
            if _is_degenerate_answer(result):
                logger.warning(
                    "generate_answer: degenerate citation-only output, retrying",
                    extra={"chat_message_id": chat_message_id, "answer": result},
                )
                retry_messages = [
                    *messages,
                    {"role": "assistant", "content": result},
                    {
                        "role": "user",
                        "content": (
                            "방금 답변은 인용 번호만 있고 설명 문장이 없습니다. "
                            "발췌문 내용을 바탕으로 완전한 문장으로 다시 설명해 주세요."
                        ),
                    },
                ]
                result = provider.generate(system_prompt, retry_messages)
            return result

        answer = _generate(context)
        if agent_steps is not None:
            agent_steps["timings_ms"]["answer"] = _elapsed_ms(answer_started)
            progress({"phase": "verifying", "subquestions": subquestions})
        verify_started = time.monotonic()

        # Agentic self-reflection: verify the answer is grounded in what was
        # retrieved. If not, broaden retrieval once and regenerate — capped at
        # exactly one extra hop so a persistently ungrounded question can't loop.
        verifier = _get_verifier_provider(db, conversation, provider, spec["backend"])
        grounding = GROUNDING_SKIPPED
        broadened = False
        if chunks:
            trace["verifier_model"] = _verifier_model_key(
                verifier, provider, conversation.model_key
            )
            grounded = _is_answer_grounded(verifier, msg.query, context, answer)
            grounding = GROUNDING_PASSED if grounded else GROUNDING_FAILED
            # 심층 검색은 이미 하위 질문별로 보강 검색을 했으므로 다시 넓혀 찾지 않는다(지연 상한)
            if not grounded and not is_deep:
                logger.info(
                    "generate_answer: reflection flagged ungrounded answer, broadening retrieval once",
                    extra={"chat_message_id": chat_message_id},
                )
                broadened_chunks = retrieval_fn(
                    db, str(conversation.user_id), msg.query, collection_id_str,
                    project_id=project_id_str, limit=_BROADEN_LIMIT,
                )
                if broadened_chunks:
                    chunks = broadened_chunks
                    context = _build_context(chunks)
                    answer = _generate(context)
                    broadened = True

        usage = getattr(provider, "last_usage", None)
        if usage:
            from app.db.models.llm_usage_log import LLMUsageLog
            from app.services.llm import estimate_cost_usd

            db.add(
                LLMUsageLog(
                    user_id=str(conversation.user_id),
                    project_id=project_id_str,
                    conversation_id=str(conversation.id),
                    provider=spec["backend"],
                    model_key=conversation.model_key,
                    input_tokens=usage["input_tokens"],
                    output_tokens=usage["output_tokens"],
                    estimated_cost_usd=estimate_cost_usd(
                        conversation.model_key, usage["input_tokens"], usage["output_tokens"]
                    ),
                )
            )

        msg.answer = answer
        msg.citations = [
            {
                "index": i + 1,
                "document_id": c["document_id"],
                "collection_id": c.get("collection_id"),
                "collection_name": c.get("collection_name"),
                "filename": c["filename"],
                "page_number": c.get("page_number"),
                "text": c["text"],
                "evidence": c.get("evidence"),
            }
            for i, c in enumerate(chunks)
        ]
        if agent_steps is not None:
            agent_steps["timings_ms"]["verify"] = _elapsed_ms(verify_started)
        msg.agent_steps = agent_steps
        trace["agent_steps"] = agent_steps
        msg.status = "DONE"
        record_answer_trace(
            db, **trace, status="DONE", answer=answer, chunks=chunks, grounding=grounding,
            broadened=broadened, usage=usage, latency_ms=_elapsed_ms(started),
        )
        db.commit()

        try:
            redis_client.delete(partial_key, f"chat_progress:{chat_message_id}")
        except Exception:
            pass

        try:
            redis_client.setex(
                cache_key,
                _ANSWER_CACHE_TTL_SECONDS,
                json.dumps({"answer": msg.answer, "citations": msg.citations, "agent_steps": msg.agent_steps,
                            "expanded_terms": msg.expanded_terms}),
            )
        except Exception:
            logger.exception("generate_answer: failed to write answer cache")

        return {"chat_message_id": chat_message_id, "status": "DONE"}

    except Exception as exc:
        logger.exception(
            "generate_answer failed", extra={"chat_message_id": chat_message_id}
        )
        db.rollback()
        try:
            msg = db.get(ChatMessage, chat_message_id)
            if msg:
                msg.status = "FAILED"
                msg.error_message = str(exc)[:500]
                if "query" in trace:
                    record_answer_trace(
                        db, **trace, status="FAILED", error_message=str(exc),
                        latency_ms=_elapsed_ms(started),
                    )
                db.commit()
        except Exception:
            logger.exception("generate_answer: failed to record failure state")
        try:
            import redis

            redis.from_url(settings.redis_url).delete(
                f"chat_partial:{chat_message_id}", f"chat_progress:{chat_message_id}",
            )
        except Exception:
            logger.warning("generate_answer: failed to clear progress keys", exc_info=True)
        return {"chat_message_id": chat_message_id, "status": "FAILED", "error": str(exc)}
    finally:
        db.close()
