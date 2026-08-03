import hashlib
import json
import logging
import re

from app.core.config import settings
from app.pipeline.celery_app import celery_app

logger = logging.getLogger(__name__)

# Exact-match answer cache TTL. Not a semantic/similarity cache — only identical
# (query, scope, model) hits reuse a cached answer. Bounds staleness after a
# document is reprocessed without needing explicit cache invalidation.
_ANSWER_CACHE_TTL_SECONDS = 3600


def _answer_cache_key(query: str, collection_id: str | None, project_id: str | None, model_key: str) -> str:
    normalized = query.strip().lower()
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"rag_answer:{model_key}:{collection_id or 'all'}:{project_id or 'none'}:{digest}"

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

# Over-fetch this many times the requested limit before BM25 reranking, mirroring
# search_service.py::perform_search's hybrid-search candidate pool.
_HYBRID_CANDIDATE_MULTIPLIER = 4


def _accessible_collection_ids(db, user_id: str, project_id: str | None = None) -> list[str]:
    from app.db.models.collection import Collection
    from app.db.models.collection_member import CollectionMember
    from app.db.models.project import Project
    from app.db.models.project_member import ProjectMember

    owned_q = db.query(Collection.id).filter(Collection.created_by == user_id)
    member_q = db.query(CollectionMember.collection_id).filter(CollectionMember.user_id == user_id)

    owned_project_rows = db.query(Project.id).filter(Project.created_by == user_id).all()
    member_project_rows = (
        db.query(ProjectMember.project_id).filter(ProjectMember.user_id == user_id).all()
    )
    user_project_ids = [str(row[0]) for row in [*owned_project_rows, *member_project_rows]]

    if project_id is not None:
        owned_q = owned_q.filter(Collection.project_id == project_id)
        member_q = member_q.join(Collection, Collection.id == CollectionMember.collection_id).filter(
            Collection.project_id == project_id
        )
        project_ids = [project_id] if project_id in user_project_ids else []
    else:
        project_ids = user_project_ids

    owned = [str(row[0]) for row in owned_q.all()]
    member_of = [str(row[0]) for row in member_q.all()]
    via_project = []
    if project_ids:
        via_project = [
            str(row[0])
            for row in db.query(Collection.id)
            .filter(
                Collection.project_id.in_(project_ids),
                Collection.restrict_to_members.is_(False),
            )
            .all()
        ]
    return list({*owned, *member_of, *via_project})


def _retrieve_chunks(
    db,
    user_id: str,
    query: str,
    collection_id: str | None,
    project_id: str | None = None,
    limit: int = 5,
) -> list[dict]:
    from app.db.models.collection import Collection
    from app.services.bm25_service import bm25_rerank
    from app.services.embedding import get_embedding_provider
    from app.services.qdrant_service import qdrant_service

    # A single collection_id was already access-checked when the conversation was
    # created (see endpoints/chat.py). With no collection_id ("search all my
    # documents", or "search this whole project" when project_id is set), every
    # collection shares one physical Qdrant collection, so an unscoped query must
    # be restricted to the user's accessible collections (optionally narrowed to
    # one project) or it would surface other users' private document text.
    collection_ids = None
    if not collection_id:
        collection_ids = _accessible_collection_ids(db, user_id, project_id=project_id)
        if not collection_ids:
            return []

    provider = get_embedding_provider()
    vector = provider.embed([query])[0]
    hits = qdrant_service.search(
        collection=settings.qdrant_collection_name,
        vector=vector,
        limit=limit * _HYBRID_CANDIDATE_MULTIPLIER,
        collection_id=collection_id,
        collection_ids=collection_ids,
    )

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
                "payload": h["payload"],
            }
            for h in hits
        ]
        # Stage 1 (recall): vector + BM25 hybrid fusion narrows to 2×limit.
        # Stage 2 (precision): cross-encoder reads each (query, chunk) pair
        # jointly and picks the final top-limit — falls back to the hybrid
        # ordering if the reranker is unavailable. Reranking scores the plain
        # "text" (not bm25_text) — a cross-encoder judges the actual passage
        # against the query, not a context-prefixed variant meant for recall.
        fused = bm25_rerank(query, candidates, text_field="bm25_text")[: limit * 2]
        reranked = cross_encoder_rerank(query, fused, text_field="text", top_k=limit)
        hits = [
            {"id": c["id"], "score": c.get("rerank_score", c["final_score"]), "payload": c["payload"]}
            for c in reranked
        ]
        record_hits([h["id"] for h in hits])

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
        }
        for h in hits
    ]


def _accessible_documents(db, user_id: str, collection_id: str | None, project_id: str | None = None) -> list:
    """Same collection-scoping rule as _retrieve_chunks/_accessible_collection_ids,
    but returns Document rows instead of Qdrant hits — used by the table/summary
    retrieval paths, which read structured fields on Document rather than
    embedded chunk text."""
    from app.db.models.document import Document

    if collection_id:
        collection_ids = [collection_id]
    else:
        collection_ids = _accessible_collection_ids(db, user_id, project_id=project_id)
        if not collection_ids:
            return []

    return (
        db.query(Document)
        .filter(Document.collection_id.in_(collection_ids), Document.status == "INDEXED")
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


@celery_app.task(name="tasks.generate_answer", queue="high", bind=True, max_retries=2)
def generate_answer(self, chat_message_id: str) -> dict:
    from app.db.models.chat_conversation import ChatConversation
    from app.db.models.chat_message import ChatMessage
    from app.db.models.project import Project
    from app.db.models.user import User
    from app.db.session import get_sync_db
    from app.services.llm import LLM_MODEL_REGISTRY, get_llm_provider

    db = get_sync_db()
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

        redis_client = redis.from_url(settings.redis_url)
        cache_key = _answer_cache_key(
            msg.query,
            str(conversation.collection_id) if conversation.collection_id else None,
            str(conversation.project_id) if conversation.project_id else None,
            conversation.model_key,
        )
        cached = redis_client.get(cache_key)
        if cached:
            cached_payload = json.loads(cached)
            msg.answer = cached_payload["answer"]
            msg.citations = cached_payload["citations"]
            msg.status = "DONE"
            db.commit()
            return {"chat_message_id": chat_message_id, "status": "DONE", "cached": True}

        spec = LLM_MODEL_REGISTRY.get(conversation.model_key)
        if spec is None:
            raise ValueError(f"Unknown model: {conversation.model_key}")

        api_key = None
        if spec["backend"] in ("openai", "anthropic"):
            api_key = _find_api_key(db, conversation, spec["backend"])
            if not api_key:
                raise ValueError(f"{spec['backend']} API 키가 등록되어 있지 않습니다")

        collection_id_str = str(conversation.collection_id) if conversation.collection_id else None
        project_id_str = str(conversation.project_id) if conversation.project_id else None

        provider = get_llm_provider(conversation.model_key, api_key=api_key)

        # Route to one of three retrieval strategies based on what the query is
        # actually asking for — see _classify_intent's docstring/prompt for the
        # 3-way split (문서 검색 / 표 데이터 질의 / 요약 조회).
        intent = _classify_intent(provider, msg.query)
        retrieval_fn = {
            "table_query": _retrieve_table_chunks,
            "summary_lookup": _retrieve_summary_chunks,
        }.get(intent, _retrieve_chunks)

        chunks = retrieval_fn(
            db, str(conversation.user_id), msg.query, collection_id_str, project_id=project_id_str
        )
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

        requester = db.get(User, conversation.user_id)
        project = db.get(Project, conversation.project_id) if conversation.project_id else None
        system_prompt = (
            (project.system_prompt if project and project.system_prompt else None)
            or (requester.system_prompt if requester and requester.system_prompt else None)
            or _SYSTEM_PROMPT
        )

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

        def _generate(ctx: str) -> str:
            messages = [*history_messages, {"role": "user", "content": f"질문: {msg.query}\n\n발췌문:\n{ctx}"}]
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

        # Agentic self-reflection: verify the answer is grounded in what was
        # retrieved. If not, broaden retrieval once and regenerate — capped at
        # exactly one extra hop so a persistently ungrounded question can't loop.
        verifier = _get_verifier_provider(db, conversation, provider, spec["backend"])
        if chunks and not _is_answer_grounded(verifier, msg.query, context, answer):
            logger.info(
                "generate_answer: reflection flagged ungrounded answer, broadening retrieval once",
                extra={"chat_message_id": chat_message_id},
            )
            broadened_chunks = retrieval_fn(
                db, str(conversation.user_id), msg.query, collection_id_str,
                project_id=project_id_str, limit=10,
            )
            if broadened_chunks:
                chunks = broadened_chunks
                context = _build_context(chunks)
                answer = _generate(context)

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
            }
            for i, c in enumerate(chunks)
        ]
        msg.status = "DONE"
        db.commit()

        try:
            redis_client.delete(partial_key)
        except Exception:
            pass

        try:
            redis_client.setex(
                cache_key,
                _ANSWER_CACHE_TTL_SECONDS,
                json.dumps({"answer": msg.answer, "citations": msg.citations}),
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
                db.commit()
        except Exception:
            logger.exception("generate_answer: failed to record failure state")
        return {"chat_message_id": chat_message_id, "status": "FAILED", "error": str(exc)}
    finally:
        db.close()
