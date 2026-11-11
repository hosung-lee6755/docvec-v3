import asyncio
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.permissions import accessible_collection_ids
from app.core.config import settings
from app.db.models.search_history import SearchHistory
from app.db.models.user import User
from app.schemas.search import SearchRequest, SearchResponse, SearchResultItem
from app.services.access_policy import (
    build_access_context,
    load_document_facts,
    qdrant_access_filter,
    visible_document_ids,
)
from app.services.bm25_service import bm25_rerank
from app.services.chunk_stats import record_hits
from app.services.dictionary_service import expand_query
from app.services.embedding import get_embedding_provider
from app.services.mmr_service import mmr_rerank
from app.services.qdrant_service import qdrant_service

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

    fetch_limit = request.limit
    if request.mode == "hybrid":
        fetch_limit = max(fetch_limit, request.limit * _HYBRID_CANDIDATE_MULTIPLIER)
    if request.diversify:
        fetch_limit = max(fetch_limit, request.limit * _MMR_CANDIDATE_MULTIPLIER)

    # 범위: 단일 컬렉션(엔드포인트가 이미 접근 확인) 또는 접근 가능한 컬렉션 전체(프로젝트로
    # 좁힐 수 있음). 모든 컬렉션이 물리 Qdrant 컬렉션 하나를 공유하므로 범위 없이 검색하면
    # 다른 사용자의 비공개 문서가 나온다.
    if request.collection_id:
        scope = [str(request.collection_id)]
    else:
        scope = await accessible_collection_ids(db, user, project_id=request.project_id)
        if not scope:
            return []

    # v3 권한: 검색 단계에서 보안등급·ACL로 거르고(qdrant_access_filter), 결과는 Postgres
    # 기준으로 한 번 더 확인한다(페이로드 동기화가 늦어도 누출되지 않게 — fail-closed).
    ctx = await build_access_context(db, user)
    hits = qdrant_service.search(
        collection=settings.qdrant_collection_name,
        vector=query_vector,
        limit=fetch_limit,
        with_vectors=request.diversify,
        query_filter=qdrant_access_filter(ctx, scope, extra=request.filters),
    )
    if hits:
        facts = await load_document_facts(db, {h["payload"].get("document_id") for h in hits})
        allowed = visible_document_ids(ctx, facts)
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

    if request.mode == "hybrid" and candidates:
        candidates = bm25_rerank(expanded_query, candidates, text_field="bm25_text")

    if request.diversify and candidates:
        relevance_field = "final_score" if request.mode == "hybrid" else "score"
        candidates = mmr_rerank(
            candidates, k=request.limit, relevance_field=relevance_field, lambda_param=_MMR_LAMBDA
        )
    else:
        candidates = candidates[: request.limit]

    results = [
        SearchResultItem(
            chunk_id=c["chunk_id"],
            score=c["score"],
            document_id=UUID(c["document_id"]),
            content=c["content"],
            metadata=c["metadata"],
            bm25_score=c.get("bm25_score"),
            final_score=c.get("final_score"),
        )
        for c in candidates
    ]

    db.add(
        SearchHistory(
            user_id=str(user.id),
            query=request.query,
            collection_id=str(request.collection_id) if request.collection_id else None,
            result_count=len(results),
            search_mode=request.mode,
            # v3 조회 감사: 결과로 돌려준 문서(중복 제거, 결과 순서 유지)
            result_document_ids=list(dict.fromkeys(str(r.document_id) for r in results)),
        )
    )
    await db.commit()

    return SearchResponse(items=results, expanded_query=expanded_query, added_terms=added_terms)


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
