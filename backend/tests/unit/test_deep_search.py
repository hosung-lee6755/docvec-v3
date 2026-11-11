"""v3 마일스톤 5 — 심층 검색의 질문 분해와 하위 질문 검색.

권한(하위 질문이 볼 수 없는 문서를 끌어오지 않는지)은 누출 매트릭스가, 채팅 작업과의 연결은
test_task_chat.py가 맡는다. 여기서는 순수 로직만 본다.
"""
from uuid import uuid4

import pytest

from app.services.agentic import deep_search, planner
from app.services.agentic.deep_search import (
    mask_step_documents,
    run_deep_search,
    search_subquestions,
    step_document_ids,
    synthesis_message,
)

Q = "2027년 영업 목표와 2026년 실적을 비교해 줘"


# -- 분해 결과 해석 --------------------------------------------------------------

@pytest.mark.parametrize("output, expected", [
    ('["2027년 영업 목표는?", "2026년 영업 실적은?"]', ["2027년 영업 목표는?", "2026년 영업 실적은?"]),
    ('하위 질문입니다.\n```json\n["2027년 영업 목표는?", "2026년 영업 실적은?"]\n```',
     ["2027년 영업 목표는?", "2026년 영업 실적은?"]),
    ("1. 2027년 영업 목표는?\n2) 2026년 영업 실적은?\n3. 두 값의 차이는?",
     ["2027년 영업 목표는?", "2026년 영업 실적은?", "두 값의 차이는?"]),
    ("- 2027년 영업 목표는?\n• 2026년 영업 실적은?", ["2027년 영업 목표는?", "2026년 영업 실적은?"]),
])
def test_subquestions_are_read_from_json_or_lists(output, expected):
    assert planner.parse_subquestions(output, Q) == expected


@pytest.mark.parametrize("output", [
    "이 질문은 나눌 필요가 없습니다.",          # 목록이 아님
    '["2027년 영업 목표는?"]',                   # 하나뿐
    '["가", "나"]',                              # 너무 짧음
    '["2027년 목표는?", "2027년 목표는?"]',      # 중복
    "",
])
def test_unusable_output_falls_back_to_the_original_question(output):
    assert planner.parse_subquestions(output, Q) == [Q]


def test_at_most_three_subquestions_are_kept():
    output = '["질문 하나요?", "질문 둘이요?", "질문 셋이요?", "질문 넷이요?"]'
    assert planner.parse_subquestions(output, Q) == ["질문 하나요?", "질문 둘이요?", "질문 셋이요?"]


def test_decompose_survives_a_model_error():
    class Broken:
        def generate(self, *_):
            raise RuntimeError("cuda oom")

    assert planner.decompose(Broken(), Q) == [Q]


# -- 하위 질문 검색 --------------------------------------------------------------

def _hit(doc, n, score=1.0):
    return {"document_id": doc, "filename": f"{doc}.pdf", "text": f"{doc}-{n}", "chunk_ref": f"{doc}-{n}", "score": score}


class Retriever:
    def __init__(self, table):
        self.table, self.calls = table, []

    def __call__(self, query, limit):
        self.calls.append((query, limit))
        return list(self.table.get(query, []))


def test_strong_results_are_used_as_is_and_merged_in_turns():
    retrieve = Retriever({
        "목표?": [_hit("goal", 1), _hit("goal", 2), _hit("goal", 3)],
        "실적?": [_hit("perf", 1), _hit("perf", 2)],
    })
    progress = []

    chunks, records = search_subquestions(Q, ["목표?", "실적?"], retrieve, progress.append)

    assert retrieve.calls == [("목표?", 4), ("실적?", 4)]
    # 한 질문의 근거가 앞자리를 다 차지하지 않도록 번갈아 모은다
    assert [c["chunk_ref"] for c in chunks] == ["goal-1", "perf-1", "goal-2", "perf-2", "goal-3"]
    assert [c["subquestion_index"] for c in chunks] == [0, 1, 0, 1, 0]
    assert [r["supplemented"] for r in records] == [False, False]
    assert records[0]["documents"] == [{"document_id": "goal", "filename": "goal.pdf"}]
    assert [p["current"] for p in progress] == [0, 1]


def test_weak_results_get_one_supplementary_search_with_the_original_question():
    retrieve = Retriever({
        "목표?": [_hit("goal", 1)],                                     # 2개 미만
        "실적?": [_hit("perf", 1, score=-3.0), _hit("perf", 2, score=-4.0)],  # 점수가 낮음
        f"{Q} 목표?": [_hit("goal", 1), _hit("plan", 1)],
        f"{Q} 실적?": [_hit("perf", 3)],
    })

    chunks, records = search_subquestions(Q, ["목표?", "실적?"], retrieve, lambda _: None)

    assert (f"{Q} 목표?", 8) in retrieve.calls and (f"{Q} 실적?", 8) in retrieve.calls
    assert [r["searches"] for r in records] == [2, 2]
    # 보강 검색에서 다시 나온 청크는 한 번만 쓴다
    assert sorted(c["chunk_ref"] for c in chunks) == ["goal-1", "perf-1", "perf-2", "perf-3", "plan-1"]


def test_evidence_is_capped():
    many = {f"질문{i}?": [_hit(f"d{i}", n) for n in range(6)] for i in range(3)}
    chunks, _ = search_subquestions(Q, list(many), Retriever(many), lambda _: None)
    assert len(chunks) == deep_search.MAX_EVIDENCE


def test_a_failed_search_is_skipped_and_the_rest_continue():
    def retrieve(query, limit):
        if query == "목표?":
            raise RuntimeError("qdrant timeout")
        return [_hit("perf", 1), _hit("perf", 2)] if query == "실적?" else []

    chunks, records = search_subquestions(Q, ["목표?", "실적?"], retrieve, lambda _: None)

    assert [c["chunk_ref"] for c in chunks] == ["perf-1", "perf-2"]
    assert [r["failed_searches"] for r in records] == [1, 0]


def test_deep_search_fails_when_every_search_fails():
    def broken(*_):
        raise RuntimeError("qdrant down")

    with pytest.raises(deep_search.DeepSearchError):
        run_deep_search(Planner('["질문 하나요?", "질문 둘이요?"]'), Q, broken, lambda _: None)


def test_chunks_without_a_ref_are_deduplicated_by_text():
    a = {"document_id": "d", "text": "같은 본문"}
    assert deep_search._chunk_key(a) == deep_search._chunk_key(dict(a))
    assert deep_search._chunk_key(a) != deep_search._chunk_key({**a, "text": "다른 본문"})


class Planner:
    def __init__(self, output):
        self.output = output

    def generate(self, *_):
        return self.output


def test_original_question_is_searched_when_subquestions_find_nothing():
    retrieve = Retriever({Q: [_hit("any", 1)]})
    result = run_deep_search(Planner('["없는 질문 하나?", "없는 질문 둘?"]'), Q, retrieve, lambda _: None)

    assert result.steps["fallback_to_original"] is True and result.steps["decomposed"] is True
    assert [c["chunk_ref"] for c in result.chunks] == ["any-1"]
    assert set(result.steps["timings_ms"]) == {"plan", "search"}


def test_undecomposed_question_is_searched_once_without_supplement():
    retrieve = Retriever({Q: [_hit("x", 1)]})
    result = run_deep_search(Planner("나눌 필요 없음"), Q, retrieve, lambda _: None)

    assert result.subquestions == [Q] and retrieve.calls == [(Q, 4)]
    assert result.steps["decomposed"] is False


def test_synthesis_prompt_lists_subquestions_only_when_decomposed():
    assert "하위 질문" not in synthesis_message(Q, [Q], "ctx")
    text = synthesis_message(Q, ["목표?", "실적?"], "[1] a.pdf: 본문")
    assert "1. 목표?" in text and "2. 실적?" in text and "[1] a.pdf: 본문" in text and "추측하지" in text


# -- 기록 가리기 -----------------------------------------------------------------

def test_step_documents_the_viewer_cannot_see_are_masked():
    seen, hidden = str(uuid4()), str(uuid4())
    steps = {"subquestions": [{"question": "q", "documents": [
        {"document_id": seen, "filename": "ok.pdf"}, {"document_id": hidden, "filename": "secret.pdf"},
    ]}]}

    assert step_document_ids(steps) == {seen, hidden}
    masked = mask_step_documents(steps, {seen})
    assert masked["subquestions"][0]["documents"] == [
        {"document_id": seen, "filename": "ok.pdf"}, {"document_id": None, "filename": None, "hidden": True},
    ]
    assert "secret.pdf" not in str(masked) and steps["subquestions"][0]["documents"][1]["filename"] == "secret.pdf"
    assert mask_step_documents(None, set()) is None



def test_weakness_uses_only_the_rerank_score_from_evidence():
    from app.services.agentic.deep_search import _is_weak

    reranked_low = [{"score": 0.9, "evidence": {"scores": {"rerank": 0.2}}}] * 2
    assert _is_weak(reranked_low) is True
    # 재순위를 끈 컬렉션의 코사인 점수(0.3)로는 약하다고 보지 않는다. 결과 수만 본다
    cosine_only = [{"score": 0.3, "evidence": {"scores": {"vector": 0.3}}}] * 2
    assert _is_weak(cosine_only) is False
    assert _is_weak(cosine_only[:1]) is True
