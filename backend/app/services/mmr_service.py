import math

# 0.7: favors relevance (70%) over diversity (30%) — standard balance for retrieval;
# queries expecting maximum diversity can override to lower values
_DEFAULT_LAMBDA = 0.7


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def mmr_rerank(
    candidates: list[dict],
    k: int,
    relevance_field: str = "score",
    vector_field: str = "vector",
    lambda_param: float = _DEFAULT_LAMBDA,
) -> list[dict]:
    """Greedy Maximal Marginal Relevance selection: picks k candidates that
    balance query relevance against redundancy with items already chosen, so
    the top results aren't all near-duplicate chunks of the same passage.
    lambda_param=1.0 reduces to sorting by relevance_field; lower values
    favor diversity more. A candidate missing vector_field is treated as
    non-redundant with everything (contributes 0 to the redundancy term)
    rather than raising, since MMR is a ranking refinement, not a hard
    dependency of search."""
    if not candidates:
        return []

    pool = list(candidates)
    selected: list[dict] = []

    while pool and len(selected) < k:
        best_idx = 0
        best_score = float("-inf")
        for i, cand in enumerate(pool):
            relevance = cand.get(relevance_field, 0.0) or 0.0
            cand_vector = cand.get(vector_field)
            selected_vectors = [s[vector_field] for s in selected if s.get(vector_field)]
            if cand_vector and selected_vectors:
                redundancy = max(_cosine(cand_vector, v) for v in selected_vectors)
            else:
                redundancy = 0.0
            mmr_score = lambda_param * relevance - (1 - lambda_param) * redundancy
            if mmr_score > best_score:
                best_score = mmr_score
                best_idx = i
        selected.append(pool.pop(best_idx))

    return selected
