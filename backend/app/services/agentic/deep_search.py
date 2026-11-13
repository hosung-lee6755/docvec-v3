"""심층 검색(v3 마일스톤 5): 하위 질문별 검색, 약한 근거 보강, 근거 병합, 종합 지시문.

검색 함수는 호출자가 넘긴다. 채팅 작업은 권한 필터와 Postgres 재확인을 거치는 `_retrieve_chunks`를
묶어 넘기므로, 하위 질문 문장이 무엇이든 그 사용자가 볼 수 없는 문서는 근거가 될 수 없다.
LLM은 분해(planner)와 종합에만 쓰고, 근거가 충분한지는 검색 결과 수와 재순위 점수로 판단한다.
"""
import hashlib
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from app.services.agentic.planner import decompose

logger = logging.getLogger(__name__)

PER_QUESTION_LIMIT = 4
SUPPLEMENT_LIMIT = 8
MAX_EVIDENCE = 10
# 이보다 적게 찾았거나 최고 점수가 이보다 낮으면 근거가 약하다고 보고 한 번 더 찾는다.
# 점수는 bge-reranker-v2-m3를 normalize=True로 부른 재순위 점수라 0~1(시그모이드)이고, 0.5가 로짓 0이다.
# 재순위를 끈 컬렉션은 코사인이나 융합 점수만 있어 같은 기준을 쓸 수 없으므로 결과 수로만 판단한다.
MIN_HITS = 2
MIN_TOP_SCORE = 0.5
# 하위 질문마다 가장 관련 높은 근거의 이 비율보다 낮은 근거는 버린다. 재순위 점수는 문서에 따라
# 절대값 차이가 커서(관련 문서도 0.004~0.04, 무관한 문서는 0.0001 이하로 실측) 고정 하한 대신
# 최고점 대비 비율을 쓴다. 무관한 문서가 "근거"로 붙어 답이 엉뚱해지던 문제를 막는다.
RELATIVE_FLOOR = 0.1

RetrieveFn = Callable[[str, int], list[dict]]
ProgressFn = Callable[[dict], None]


class DeepSearchError(RuntimeError):
    """심층 검색의 검색이 하나도 성공하지 못했다."""


@dataclass(frozen=True)
class DeepSearchResult:
    subquestions: list[str]
    chunks: list[dict]
    steps: dict


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _is_weak(hits: list[dict]) -> bool:
    if len(hits) < MIN_HITS:
        return True
    scores = [_relevance(h) for h in hits]
    top = max((s for s in scores if isinstance(s, (int, float))), default=None)
    return top is not None and top < MIN_TOP_SCORE


def _relevance(hit: dict) -> float | None:
    """재순위 점수. 검색 결과에 근거 설명(evidence)이 있으면 그 안의 재순위 점수만 쓴다."""
    evidence = hit.get("evidence")
    if isinstance(evidence, dict):
        return (evidence.get("scores") or {}).get("rerank")
    return hit.get("score")


def prune_unrelated(hits: list[dict]) -> list[dict]:
    """재순위 점수가 최고점의 RELATIVE_FLOOR배보다 낮거나 0인 근거를 뺀다.
    재순위 점수가 없는 결과(재순위를 끈 컬렉션)는 판단 근거가 없으므로 그대로 둔다.
    코사인이나 BM25 같은 다른 점수는 척도가 달라 비율로 비교하지 않는다."""
    scores = [
        ((h.get("evidence") or {}).get("scores") or {}).get("rerank") if isinstance(h.get("evidence"), dict) else None
        for h in hits
    ]
    numeric = [s for s in scores if isinstance(s, (int, float))]
    if not numeric:
        return hits
    floor = max(numeric) * RELATIVE_FLOOR
    return [
        h for h, s in zip(hits, scores)
        if not isinstance(s, (int, float)) or (s > 0 and s >= floor)
    ]


def _chunk_key(chunk: dict) -> str:
    if chunk.get("chunk_ref"):
        return chunk["chunk_ref"]
    digest = hashlib.sha256((chunk.get("text") or "").encode("utf-8")).hexdigest()
    return f"{chunk.get('document_id')}:{digest}"


def _try_retrieve(retrieve: RetrieveFn, query: str, limit: int) -> list[dict] | None:
    """검색 한 번. 실패하면 None을 돌려줘 나머지 하위 질문은 계속 찾게 한다."""
    try:
        return retrieve(query, limit)
    except Exception:
        logger.warning("deep search: retrieval failed", exc_info=True)
        return None


def _documents(hits: list[dict]) -> list[dict]:
    seen: dict[str, str | None] = {}
    for h in hits:
        doc_id = h.get("document_id")
        if doc_id and doc_id not in seen:
            seen[doc_id] = h.get("filename")
    return [{"document_id": d, "filename": f} for d, f in seen.items()]


def search_subquestions(query: str, subquestions: list[str], retrieve: RetrieveFn,
                        progress: ProgressFn) -> tuple[list[dict], list[dict]]:
    """(병합된 근거, 하위 질문별 기록). 근거는 하위 질문 순서대로 모으고 중복을 뺀다."""
    per_question: list[list[dict]] = []
    records: list[dict] = []
    for index, question in enumerate(subquestions):
        progress({"phase": "searching", "subquestions": subquestions, "current": index})
        first = _try_retrieve(retrieve, question, PER_QUESTION_LIMIT)
        failed = int(first is None)
        hits = first or []
        supplemented = False
        if _is_weak(hits) and question != query:
            # 하위 질문만으로는 맥락이 모자랄 수 있어 원 질문을 붙여 더 넓게 찾는다
            extra = _try_retrieve(retrieve, f"{query} {question}", SUPPLEMENT_LIMIT)
            failed += int(extra is None)
            known = {_chunk_key(h) for h in hits}
            hits = hits + [h for h in extra or [] if _chunk_key(h) not in known]
            supplemented = True
        related = prune_unrelated(hits)
        per_question.append(related)
        records.append({
            "question": question, "searches": 2 if supplemented else 1, "supplemented": supplemented,
            "failed_searches": failed, "hit_count": len(related), "dropped_unrelated": len(hits) - len(related),
            "documents": _documents(related),
        })

    merged: list[dict] = []
    seen: set[str] = set()
    # 하위 질문마다 한 개씩 돌아가며 뽑아, 앞 질문의 근거가 상한을 다 차지하지 않게 한다
    for rank in range(max((len(h) for h in per_question), default=0)):
        for index, hits in enumerate(per_question):
            if rank < len(hits) and _chunk_key(hits[rank]) not in seen and len(merged) < MAX_EVIDENCE:
                seen.add(_chunk_key(hits[rank]))
                merged.append({**hits[rank], "subquestion_index": index})
    return merged, records


def run_deep_search(provider, query: str, retrieve: RetrieveFn, progress: ProgressFn) -> DeepSearchResult:
    started = time.monotonic()
    progress({"phase": "planning"})
    subquestions = decompose(provider, query)
    plan_ms = _elapsed_ms(started)

    search_started = time.monotonic()
    chunks, records = search_subquestions(query, subquestions, retrieve, progress)
    searches = sum(r["searches"] for r in records)
    failures = sum(r["failed_searches"] for r in records)
    fallback = False
    if not chunks and subquestions != [query]:
        # 하위 질문으로 아무것도 못 찾았으면 원 질문으로 한 번 더 찾는다
        found = _try_retrieve(retrieve, query, PER_QUESTION_LIMIT)
        searches, failures = searches + 1, failures + int(found is None)
        chunks = [{**c, "subquestion_index": None} for c in prune_unrelated(found or [])]
        fallback = True
    if failures and failures == searches:
        # 검색이 모두 실패했는데 "근거 없음"으로 답하면 장애가 가려지므로 작업을 실패로 끝낸다
        raise DeepSearchError("심층 검색의 검색이 모두 실패했습니다")
    steps = {
        "subquestions": records,
        "decomposed": subquestions != [query],
        "fallback_to_original": fallback,
        "evidence_count": len(chunks),
        "timings_ms": {"plan": plan_ms, "search": _elapsed_ms(search_started)},
    }
    return DeepSearchResult(subquestions=subquestions, chunks=chunks, steps=steps)


def _normalized_id(value) -> str | None:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError):
        return None


def step_document_ids(steps: dict | None) -> set[str]:
    """검색 과정 기록에 나오는 문서 id(정규화한 UUID 문자열)."""
    ids = {
        _normalized_id(d.get("document_id"))
        for q in (steps or {}).get("subquestions") or [] for d in q.get("documents") or []
    }
    return ids - {None}


def mask_step_documents(steps: dict | None, visible: set[str]) -> dict | None:
    """보는 사람이 지금 볼 수 없는 문서는 id와 파일명을 지운다. 인용 가림과 같은 기준이다."""
    if not steps or not steps.get("subquestions"):
        return steps
    masked = []
    for q in steps["subquestions"]:
        docs = [
            d if _normalized_id(d.get("document_id")) in visible
            else {"document_id": None, "filename": None, "hidden": True}
            for d in q.get("documents") or []
        ]
        masked.append({**q, "documents": docs})
    return {**steps, "subquestions": masked}


def unanswered_indexes(steps: dict | None) -> set[int]:
    """관련 근거를 하나도 찾지 못한 하위 질문의 번호(0부터)."""
    records = (steps or {}).get("subquestions") or []
    return {i for i, record in enumerate(records) if not record.get("hit_count")}


def synthesis_message(query: str, subquestions: list[str], context: str,
                      unanswered: set[int] | frozenset[int] = frozenset()) -> str:
    """종합 단계의 사용자 메시지. 시스템 프롬프트(인용 규칙)는 일반 답변과 같은 것을 쓴다.
    unanswered에 든 하위 질문은 관련 근거가 없다고 미리 알려, 다른 하위 질문의 발췌문을
    끌어다 억지로 답을 만들지 않게 한다."""
    if len(subquestions) < 2:
        return f"질문: {query}\n\n발췌문:\n{context}"
    listed = "\n".join(
        f"{i}. {q}" + (" (관련 발췌문 없음)" if i - 1 in unanswered else "")
        for i, q in enumerate(subquestions, 1)
    )
    return (
        f"질문: {query}\n\n"
        f"이 질문을 다음 하위 질문으로 나눠 사내 문서를 찾았습니다.\n{listed}\n\n"
        f"발췌문:\n{context}\n\n"
        "하위 질문마다 발췌문에서 확인한 내용을 근거 번호와 함께 정리한 뒤, 원래 질문에 대한 답을 종합하세요. "
        "발췌문이 그 하위 질문과 직접 관련이 없으면 쓰지 마세요. "
        "\"관련 발췌문 없음\"으로 표시한 하위 질문과 발췌문에서 찾지 못한 하위 질문은 "
        "찾지 못했다고 한 문장으로만 밝히고 추측하지 마세요."
    )
