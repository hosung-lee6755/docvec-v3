"""검색 화면의 교차 인코더 재순위(2026-11-27, 사용자 지적 "검색 결과의 신뢰성이 떨어짐").

검색 화면은 지금까지 벡터 점수와 키워드 점수의 합으로만 순서를 정했다. 채팅은 그 뒤에 교차 인코더가 질문과 발췌문을
함께 읽어 다시 고른다. 같은 질문에 검색 화면과 채팅 근거가 달랐던 까닭이다.

교차 인코더는 API 프로세스에 올리지 않는다. CPU 에서는 쌍 하나에 수 초가 걸리고, 모델을 올리는 동안 다른 요청이 멈춘
일이 있었다. 모델이 이미 올라 있는 worker-embed(llm 큐)에 점수만 맡기고, 정한 시간 안에 답이 없으면 재순위 없이 낸다.
문서 임베딩이 몰려 워커가 바쁠 때 검색이 멈추지 않게 하기 위해서다.
"""
from __future__ import annotations

import asyncio
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)

RERANK_TASK = "tasks.rerank_texts"
RERANK_QUEUE = "llm"


def _scores_from_worker(query: str, texts: list[str]) -> list[float] | None:
    from app.pipeline.celery_app import celery_app

    try:
        # 재시도하지 않는다. 브로커가 멈췄을 때 연결을 거듭 시도하느라 검색이 수십 초 멈추지 않게 한다
        result = celery_app.send_task(RERANK_TASK, args=[query, texts], queue=RERANK_QUEUE, retry=False)
        scores = result.get(timeout=settings.search_rerank_timeout_seconds, propagate=False)
    except Exception as exc:  # noqa: BLE001 - 시간 초과와 브로커 오류 모두 재순위 없이 낸다
        logger.warning("search rerank skipped: %s", type(exc).__name__)
        return None
    if not isinstance(scores, list) or len(scores) != len(texts):
        return None
    return [float(s) for s in scores]


async def rerank_candidates(
    query: str, candidates: list[dict], *, text_field: str, limit: int,
) -> tuple[list[dict], bool]:
    """교차 인코더 점수 순으로 고른 상위 limit 개와 재순위를 했는지. 못 하면 들어온 순서 그대로 자른다."""
    if not candidates:
        return [], False
    texts = [c.get(text_field) or "" for c in candidates]
    scores = await asyncio.to_thread(_scores_from_worker, query, texts)
    if scores is None:
        return candidates[:limit], False
    scored = [{**c, "rerank_score": s} for c, s in zip(candidates, scores, strict=True)]
    ranked = sorted(scored, key=lambda c: c["rerank_score"], reverse=True)
    return ranked[:limit], True
