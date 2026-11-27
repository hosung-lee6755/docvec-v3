"""검색 화면 재순위(2026-11-27): 워커 점수로 다시 고르고, 답이 없으면 들어온 순서를 지킨다."""
import pytest

from app.services import search_rerank

# conftest 의 autouse 대체보다 먼저(수집 시점에) 원래 함수를 잡아 둔다
_REAL_SCORES_FROM_WORKER = search_rerank._scores_from_worker

CANDIDATES = [
    {"chunk_id": "a", "content": "제5조(근무요령) 근무시간 중 신분증"},
    {"chunk_id": "b", "content": "제3조(근무제 및 근무시간) 격일제"},
    {"chunk_id": "c", "content": "제1조(목적)"},
]


@pytest.mark.asyncio
async def test_candidates_are_reordered_by_worker_scores(monkeypatch):
    monkeypatch.setattr(search_rerank, "_scores_from_worker", lambda q, texts: [0.2, 0.9, 0.1])

    ranked, reranked = await search_rerank.rerank_candidates("근무시간", CANDIDATES, text_field="content", limit=2)

    assert reranked is True
    assert [c["chunk_id"] for c in ranked] == ["b", "a"]
    assert ranked[0]["rerank_score"] == 0.9
    assert "rerank_score" not in CANDIDATES[1]  # 들어온 후보는 바꾸지 않는다


@pytest.mark.asyncio
async def test_without_worker_answer_the_input_order_is_kept():
    ranked, reranked = await search_rerank.rerank_candidates("근무시간", CANDIDATES, text_field="content", limit=2)

    assert reranked is False
    assert [c["chunk_id"] for c in ranked] == ["a", "b"]


@pytest.mark.asyncio
async def test_empty_candidates_skip_the_worker():
    assert await search_rerank.rerank_candidates("q", [], text_field="content", limit=5) == ([], False)


class _FakeApp:
    def __init__(self, answer=None, error=None):
        self.answer, self.error, self.kwargs = answer, error, None

    def send_task(self, *args, **kwargs):
        self.kwargs = kwargs
        if self.error:
            raise self.error
        answer = self.answer

        class _Result:
            def get(self, timeout, propagate):
                return answer

        return _Result()


@pytest.mark.parametrize("answer", [[0.5], "oops", None])
def test_worker_answer_of_wrong_shape_is_ignored(monkeypatch, answer):
    import app.pipeline.celery_app as celery_module

    fake = _FakeApp(answer=answer)
    monkeypatch.setattr(celery_module, "celery_app", fake)

    assert _REAL_SCORES_FROM_WORKER("q", ["x", "y"]) is None
    assert fake.kwargs["retry"] is False  # 브로커 재시도로 검색이 멈추지 않게 한다


def test_worker_scores_are_returned_as_floats(monkeypatch):
    import app.pipeline.celery_app as celery_module

    monkeypatch.setattr(celery_module, "celery_app", _FakeApp(answer=[1, 0.25]))

    assert _REAL_SCORES_FROM_WORKER("q", ["x", "y"]) == [1.0, 0.25]


def test_broker_error_means_no_rerank(monkeypatch):
    import app.pipeline.celery_app as celery_module

    monkeypatch.setattr(celery_module, "celery_app", _FakeApp(error=ConnectionError("down")))

    assert _REAL_SCORES_FROM_WORKER("q", ["x"]) is None


@pytest.mark.parametrize(("argv", "expected"), [
    (["celery", "worker", "-Q", "llm,embed"], True),
    (["celery", "worker", "--queues=llm"], True),
    (["celery", "worker", "-Qllm,embed"], True),
    (["celery", "worker", "-Q", "critical,high,normal,low"], False),
    (["celery", "worker", "-Q", "extract"], False),
    (["uvicorn", "app.main:app"], False),
])
def test_only_the_llm_worker_warms_up_the_reranker(argv, expected):
    from app.pipeline.celery_app import consumes_queue

    assert consumes_queue(argv, "llm") is expected
