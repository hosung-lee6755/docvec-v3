import asyncio
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.permissions import accessible_collection_ids
from app.core.config import settings
from app.db.models.search_history import SearchHistory
from app.db.models.user import User
from app.schemas.search import AppliedSearchSettings, SearchRequest, SearchResponse, SearchResultItem
from app.services.access_policy import (
    build_access_context,
    load_document_facts,
    qdrant_access_filter,
    retrievable_document_ids,
)
from app.services.bm25_service import bm25_rerank
from app.services.chunk_stats import record_hits
from app.services.dictionary_service import expand_query
from app.services.embedding import get_embedding_provider
from app.services.lexical_index import hybrid_query_vector
from app.services.mmr_service import mmr_rerank
from app.services.qdrant_service import qdrant_service
from app.services.retrieval_evidence import matched_terms, ocr_evidence, page_confidences
from app.services.search_rerank import rerank_candidates
from app.services.search_settings import DEFAULT_SEARCH_SETTINGS, stored_collection_search_settings

# 4: hybrid search (vector + BM25) needs broader initial candidate pool because
# the rerank step may substantially reorder results; 3–4x fetch buffer prevents
# trimming away candidates that would rise on reranking
_HYBRID_CANDIDATE_MULTIPLIER = 4
# 3: MMR diversity selection needs fewer candidates than hybrid reranking since
# the greedy algorithm evaluates redundancy against already-selected items,
# diminishing returns beyond 3x the requested limit
_MMR_CANDIDATE_MULTIPLIER = 3
# 0.7: favors relevance (70%) over diversity (30%) — standard balance for retrieval;
# queries expecting maximum diversity can override to lower values
_MMR_LAMBDA = 0.7
# 재순위할 후보는 결과 수의 두 배다(채팅 _rank_candidates 와 같다)
_RERANK_POOL_MULTIPLIER = 2
# 교차 인코더가 읽는 글. 채팅과 같이 문서 제목과 절 경로를 붙인 글(bm25_text)이다. 본문(content)만 읽히면
# 조 제목에 답이 있는 규정에서 순위가 떨어졌다(2026-11-27 골든 쿼리 비교, pipeline/tasks/chat.py)
_RERANK_TEXT_FIELD = "bm25_text"


def _embed_query(query: str) -> list[float]:
    provider = get_embedding_provider()
    return provider.embed([query])[0]


async def perform_search(
    db: AsyncSession, user: User, request: SearchRequest
) -> SearchResponse:
    # Dictionary-driven synonym rewrite (SEARCH_EXPAND entries only) — cheap
    # in-memory dict lookups, so run inline like bm25_rerank below rather than
    # via asyncio.to_thread (that's reserved for the genuinely CPU-heavy
    # embedding call, which blocks the whole process — see comment below).
    expanded_query, added_terms = expand_query(request.query)

    # Model load (cold start) and inference are synchronous/CPU-bound; running them
    # inline would block the single event loop for the whole API process, freezing
    # every other request (this caused a real incident: a cold-start model download
    # froze uploads and document listing for all users). Offload to a worker thread.
    query_vector = await asyncio.to_thread(_embed_query, expanded_query)

    # v3 마일스톤 6: 요청에 없으면 컬렉션 검색 설정을 따르고, 설정이 없으면 채팅과 같은 기본값(하이브리드, 재순위)이다.
    # 예전에는 설정이 없으면 의미 검색만 해서 같은 질문에 검색 화면과 채팅의 근거가 달랐다(2026-11-27).
    stored = await stored_collection_search_settings(db, request.collection_id)
    collection_settings = stored or DEFAULT_SEARCH_SETTINGS
    mode = request.mode or collection_settings.mode
    diversify = collection_settings.diversify if request.diversify is None else request.diversify
    applied = AppliedSearchSettings(
        mode=mode, diversify=diversify, vector_weight=collection_settings.vector_weight,
        rerank_in_chat=collection_settings.rerank,
        # 저장된 컬렉션 설정과 실제로 쓴 값이 같을 때만 "컬렉션 설정 기준"이라고 알린다
        from_collection=stored is not None and mode == stored.mode and diversify == stored.diversify,
    )

    fetch_limit = request.limit
    if mode == "hybrid":
        fetch_limit = max(fetch_limit, request.limit * _HYBRID_CANDIDATE_MULTIPLIER)
    if diversify:
        fetch_limit = max(fetch_limit, request.limit * _MMR_CANDIDATE_MULTIPLIER)

    # 범위: 단일 컬렉션(엔드포인트가 이미 접근 확인) 또는 접근 가능한 컬렉션 전체(프로젝트로
    # 좁힐 수 있음). 모든 컬렉션이 물리 Qdrant 컬렉션 하나를 공유하므로 범위 없이 검색하면
    # 다른 사용자의 비공개 문서가 나온다.
    if request.collection_id:
        scope = [str(request.collection_id)]
    else:
        scope = await accessible_collection_ids(db, user, project_id=request.project_id)
        if not scope:
            # 볼 수 있는 컬렉션이 없으면 빈 결과다. 예전에는 빈 목록을 돌려 응답 형식 검사에서 500 이 났다(2026-11-27)
            return SearchResponse(items=[], expanded_query=expanded_query, added_terms=added_terms, applied=applied)

    # v3 권한: 검색 단계에서 보안등급·ACL로 거르고(qdrant_access_filter), 결과는 Postgres
    # 기준으로 한 번 더 확인한다(페이로드 동기화가 늦어도 누출되지 않게 — fail-closed).
    ctx = await build_access_context(db, user)
    hits = qdrant_service.search(
        collection=settings.qdrant_collection_name,
        vector=query_vector,
        limit=fetch_limit,
        with_vectors=diversify,
        query_filter=qdrant_access_filter(ctx, scope, extra=request.filters),
        lexical=await asyncio.to_thread(hybrid_query_vector, expanded_query, mode),
        lexical_scope=scope,
    )
    if hits:
        facts = await load_document_facts(db, {h["payload"].get("document_id") for h in hits})
        allowed = retrievable_document_ids(ctx, facts)
        hits = [h for h in hits if h["payload"].get("document_id") in allowed]
    if hits:
        await asyncio.to_thread(record_hits, [h["id"] for h in hits])

    candidates = [
        {
            "chunk_id": h["id"],
            "score": h["score"],
            "document_id": h["payload"].get(
                "document_id", "00000000-0000-0000-0000-000000000000"
            ),
            "content": h["payload"].get("text", ""),
            # Contextual BM25 — index_text carries the context-prefixed text when
            # available; falls back to the plain content for points indexed before
            # this field existed. "content" above (returned to the caller) always
            # stays the pure original chunk text.
            "bm25_text": h["payload"].get("index_text") or h["payload"].get("text", ""),
            "metadata": {
                k: v for k, v in h["payload"].items() if k not in ("text", "document_id")
            },
            "vector": h.get("vector"),
        }
        for h in hits
    ]

    if mode == "hybrid" and candidates:
        weight = collection_settings.vector_weight
        candidates = bm25_rerank(expanded_query, candidates, text_field="bm25_text",
                                 alpha_vector=weight, alpha_bm25=round(1 - weight, 4))

    # 채팅과 같은 2단계: 후보를 결과 수의 두 배로 추린 뒤 교차 인코더가 다시 고른다(services/search_rerank.py)
    use_rerank = collection_settings.rerank
    pool_size = request.limit * _RERANK_POOL_MULTIPLIER if use_rerank else request.limit
    if diversify and candidates:
        relevance_field = "final_score" if mode == "hybrid" else "score"
        candidates = mmr_rerank(
            candidates, k=pool_size, relevance_field=relevance_field, lambda_param=_MMR_LAMBDA
        )
    else:
        candidates = candidates[:pool_size]
    reranked = False
    if use_rerank:
        candidates, reranked = await rerank_candidates(
            request.query, candidates, text_field=_RERANK_TEXT_FIELD, limit=request.limit,
        )
    applied = applied.model_copy(update={"reranked": reranked})

    evidence = await _result_evidence(db, expanded_query, candidates)
    places = await _result_places(db, candidates)
    results = [
        SearchResultItem(
            chunk_id=c["chunk_id"],
            score=c["score"],
            document_id=UUID(c["document_id"]),
            content=c["content"],
            metadata=c["metadata"],
            bm25_score=c.get("bm25_score"),
            final_score=c.get("final_score"),
            rerank_score=c.get("rerank_score"),
            evidence=item_evidence,
            **place,
        )
        for c, item_evidence, place in zip(candidates, evidence, places)
    ]

    db.add(
        SearchHistory(
            user_id=str(user.id),
            query=request.query,
            collection_id=str(request.collection_id) if request.collection_id else None,
            result_count=len(results),
            search_mode=mode,
            # v3 조회 감사: 결과로 돌려준 문서(중복 제거, 결과 순서 유지)
            result_document_ids=list(dict.fromkeys(str(r.document_id) for r in results)),
        )
    )
    await db.commit()

    return SearchResponse(items=results, expanded_query=expanded_query, added_terms=added_terms, applied=applied)


async def _result_evidence(db: AsyncSession, query: str, candidates: list[dict]) -> list[dict]:
    """결과마다 질문과 겹친 낱말과 그 쪽의 OCR 신뢰도. 형태소 분석은 CPU를 쓰므로 스레드로 넘긴다."""
    if not candidates:
        return []
    terms = await asyncio.to_thread(matched_terms, query, [c["content"] for c in candidates])
    confidences = await page_confidences(db, {c["document_id"] for c in candidates})
    return [
        {"matched_terms": matched,
         **ocr_evidence(confidences, c["document_id"], c["metadata"].get("page_number"))}
        for c, matched in zip(candidates, terms)
    ]


async def _result_places(db: AsyncSession, candidates: list[dict]) -> list[dict]:
    """결과마다 프로젝트·컬렉션·문서 이름, 쪽 범위, 절 경로. 채팅 인용과 같은 정보다(2026-11-27).
    청크 행을 찾지 못하면(예전 색인) 페이로드의 시작 쪽만 쓴다."""
    from app.services.source_places import chunk_places, collection_places

    if not candidates:
        return []
    collections = await collection_places(db, {c["metadata"].get("collection_id") for c in candidates} - {None})
    chunks = await chunk_places(db, {str(c["chunk_id"]): c["document_id"] for c in candidates})
    places = []
    for c in candidates:
        meta = c["metadata"]
        col = collections.get(str(meta.get("collection_id")))
        chunk = chunks.get(str(c["chunk_id"]))
        page = (chunk.page_start if chunk else None) or meta.get("page_number")
        places.append({
            "filename": meta.get("filename"),
            "collection_id": meta.get("collection_id"),
            "collection_name": col.collection_name if col else None,
            "project_id": col.project_id if col else None,
            "project_name": col.project_name if col else None,
            "page_number": page if isinstance(page, int) else None,
            "page_end": chunk.page_end if chunk else None,
            "section_path": chunk.section_path if chunk else None,
        })
    return places


async def list_search_history(
    db: AsyncSession, user_id: UUID, limit: int = 20
) -> list[SearchHistory]:
    result = await db.execute(
        select(SearchHistory)
        .where(SearchHistory.user_id == str(user_id))
        .order_by(SearchHistory.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())
