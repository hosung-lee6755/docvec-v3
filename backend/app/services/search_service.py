import asyncio
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.permissions import accessible_collection_ids
from app.core.config import settings
from app.db.models.search_history import SearchHistory
from app.db.models.user import User
from app.schemas.search import SearchRequest, SearchResponse, SearchResultItem
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

    # With no collection_id ("search all my documents"), every collection shares one
    # physical Qdrant collection, so an unscoped query must be restricted to this
    # user's own accessible collections or it would return every user's private
    # document text (see chat.py's _retrieve_chunks, which already does this).
    collection_ids = None
    if not request.collection_id:
        collection_ids = await accessible_collection_ids(
            db, user, project_id=request.project_id
        )
        if not collection_ids:
            return []

    hits = qdrant_service.search(
        collection=settings.qdrant_collection_name,
        vector=query_vector,
        limit=fetch_limit,
        collection_id=str(request.collection_id) if request.collection_id else None,
        collection_ids=collection_ids,
        filters=request.filters,
        with_vectors=request.diversify,
    )
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
