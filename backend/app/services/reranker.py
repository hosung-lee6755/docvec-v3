import logging

logger = logging.getLogger(__name__)

_MODEL_NAME = "BAAI/bge-reranker-v2-m3"

_reranker = None
_load_failed = False


def _get_reranker():
    """Lazy singleton. Loading can fail (download error, GPU OOM next to the
    resident LLM + embedder) — in that case we permanently fall back to the
    hybrid ordering for this process instead of retrying every request."""
    global _reranker, _load_failed
    if _reranker is None and not _load_failed:
        try:
            from FlagEmbedding import FlagReranker

            _reranker = FlagReranker(_MODEL_NAME, use_fp16=True)
            logger.info("cross-encoder reranker loaded", extra={"model": _MODEL_NAME})
        except Exception:
            logger.exception("reranker load failed; hybrid ordering will be used as-is")
            _load_failed = True
    return _reranker


def cross_encoder_rerank(
    query: str, candidates: list[dict], text_field: str = "text", top_k: int | None = None
) -> list[dict]:
    """Final-stage precision rerank: scores each (query, chunk) pair jointly
    with a cross-encoder, which reads both texts together — substantially more
    accurate than the bi-encoder cosine + BM25 fusion it follows. Returns the
    input unchanged (trimmed to top_k) on any failure."""
    def _trim(items: list[dict]) -> list[dict]:
        return items if top_k is None else items[:top_k]

    reranker = _get_reranker()
    if reranker is None or not candidates:
        return _trim(candidates)
    try:
        pairs = [[query, c.get(text_field, "")] for c in candidates]
        scores = reranker.compute_score(pairs, normalize=True)
        if not isinstance(scores, list):
            scores = [scores]
        for c, s in zip(candidates, scores):
            c["rerank_score"] = float(s)
        ranked = sorted(candidates, key=lambda c: c.get("rerank_score", 0.0), reverse=True)
        return _trim(ranked)
    except Exception:
        logger.exception("rerank scoring failed; returning original order")
        return _trim(candidates)
