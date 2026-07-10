from rank_bm25 import BM25Okapi


def _tokenize(text: str) -> list[str]:
    return text.lower().split()


def bm25_rerank(
    query: str,
    candidates: list[dict],
    text_field: str = "text",
    alpha_vector: float = 0.6,
    alpha_bm25: float = 0.4,
) -> list[dict]:
    """Rerank candidates by combining vector score with BM25 keyword score.

    candidates: list of dicts with at least {text_field: str, "score": float}
    Returns candidates sorted by final_score descending, with "final_score" added.
    """
    if not candidates:
        return []

    corpus = [_tokenize(c[text_field]) for c in candidates]
    bm25 = BM25Okapi(corpus)
    raw_scores = bm25.get_scores(_tokenize(query))

    max_bm25 = max(raw_scores) if max(raw_scores) > 0 else 1.0
    normalized = [s / max_bm25 for s in raw_scores]

    results = []
    for i, candidate in enumerate(candidates):
        vector_score = candidate.get("score", 0.0)
        final = alpha_vector * vector_score + alpha_bm25 * normalized[i]
        results.append({**candidate, "bm25_score": normalized[i], "final_score": final})

    results.sort(key=lambda x: x["final_score"], reverse=True)
    return results
