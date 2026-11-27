import logging
import threading

logger = logging.getLogger(__name__)

_MODEL_NAME = "BAAI/bge-reranker-v2-m3"

_reranker = None
_load_failed = False
_load_lock = threading.Lock()


def _has_gpu() -> bool:
    try:
        import torch

        return bool(torch.cuda.is_available())
    except Exception:
        return False


def _get_reranker():
    """Lazy singleton. Loading can fail (download error, OOM) — in that case
    we permanently fall back to the hybrid ordering for this process instead
    of retrying every request.

    fp16은 GPU에서만 켠다. 채팅은 worker-embed 한 프로세스에서 LLM·임베딩과 함께 돌아 fp32(약 2.1GB)면
    12GB GPU가 빠듯하다. fp16은 메모리를 반으로 줄이고 순위는 거의 같다. CPU(api 컨테이너의 검색 화면)는
    fp16을 가속하지 못해 쌍 하나에 약 8.7초가 걸리므로 fp32를 유지한다."""
    global _reranker, _load_failed
    # 워커 시작 때 미리 올리는 스레드(warm_up_in_background)와 첫 작업이 겹쳐도 한 번만 올린다
    with _load_lock:
        if _reranker is None and not _load_failed:
            try:
                from FlagEmbedding import FlagReranker

                _reranker = FlagReranker(_MODEL_NAME, use_fp16=_has_gpu())
                logger.info("cross-encoder reranker loaded", extra={"model": _MODEL_NAME})
            except Exception:
                logger.exception("reranker load failed; hybrid ordering will be used as-is")
                _load_failed = True
    return _reranker


def warm_up_in_background() -> None:
    """모델을 미리 올린다. 검색 화면은 재순위 답을 몇 초만 기다리므로, 워커를 다시 띄운 직후 첫 검색에서
    모델을 올리느라 시간을 넘겨 재순위가 빠지는 일을 막는다(2026-11-27)."""
    threading.Thread(target=_get_reranker, name="reranker-warm-up", daemon=True).start()


def score_texts(query: str, texts: list[str]) -> list[float] | None:
    """(질문, 글) 쌍마다 교차 인코더 점수(0~1). 모델이 없거나 실패하면 None.
    검색 화면이 워커에 재순위를 맡길 때 쓴다(tasks.rerank_texts, 2026-11-27)."""
    reranker = _get_reranker()
    if reranker is None or not texts:
        return None
    try:
        scores = reranker.compute_score([[query, t] for t in texts], normalize=True)
        return [float(s) for s in (scores if isinstance(scores, list) else [scores])]
    except Exception:
        logger.exception("rerank scoring failed")
        return None


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
