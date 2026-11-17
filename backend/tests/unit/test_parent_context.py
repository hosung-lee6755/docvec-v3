"""Parent Retrieval 문맥 확장(services/parent_context.py, 2026-11-13)."""
import pytest

from app.services import parent_context as pc


def test_expand_window_grows_both_ways_within_budget():
    texts = ["aaaa", "bbbb", "HIT!", "cccc", "dddd"]

    assert pc.expand_window(texts, 2, max_chars=12) == [1, 2, 3]
    assert pc.expand_window(texts, 2, max_chars=100) == [0, 1, 2, 3, 4]


def test_expand_window_keeps_hit_even_when_it_alone_exceeds_budget():
    assert pc.expand_window(["x" * 50, "y"], 0, max_chars=10) == [0]


def test_expand_window_stops_at_a_blocked_side_without_gaps():
    # 왼쪽 이웃이 길어 막히면 그 너머의 짧은 청크를 건너뛰어 붙이지 않는다
    texts = ["s", "L" * 100, "HIT", "r"]

    assert pc.expand_window(texts, 2, max_chars=10) == [2, 3]


def test_expand_window_does_not_cross_skipped_chunks():
    texts = ["a", "b", "HIT", "c"]

    assert pc.expand_window(texts, 2, max_chars=100, skip={1}) == [2, 3]


def _chunk(ref, text, kind="chunk"):
    return {"chunk_ref": ref, "text": text, "source_kind": kind, "filename": "f.pdf"}


@pytest.fixture
def siblings(monkeypatch):
    """parent P1 = c1..c4(c3는 검색 제외라 벡터 DB 본문이 없다), parent P2 = d1 하나."""
    parent_of = {"c1": "P1", "c2": "P1", "c3": "P1", "c4": "P1", "d1": "P2"}
    children = {"P1": ["c1", "c2", "c3", "c4"], "P2": ["d1"]}
    monkeypatch.setattr(pc, "_sibling_rows", lambda db, ids: (parent_of, children))
    monkeypatch.setattr(pc, "_searchable_texts", lambda ids: {"c1": "one", "c2": "two", "c4": "four", "d1": "solo"})


def test_attach_adds_neighbouring_searchable_siblings(siblings):
    out = pc.attach_parent_context(None, [_chunk("c2", "two")], max_chars=100)

    # c3(검색 제외)는 빠지고 c1, c2, c4가 순서대로 이어진다
    assert out[0]["context_text"] == "one\ntwo\nfour"
    assert out[0]["text"] == "two"


def test_attach_returns_new_dicts_and_keeps_input_unchanged(siblings):
    original = [_chunk("c2", "two")]

    out = pc.attach_parent_context(None, original, max_chars=100)

    assert "context_text" not in original[0]
    assert out[0] is not original[0]


def test_single_child_parent_and_non_chunk_sources_are_left_as_is(siblings):
    summary = _chunk(None, "요약", kind="summary")

    out = pc.attach_parent_context(None, [_chunk("d1", "solo"), summary], max_chars=100)

    assert "context_text" not in out[0]
    assert out[1] is summary


def test_later_hit_does_not_repeat_chunks_already_in_an_earlier_context(siblings):
    out = pc.attach_parent_context(None, [_chunk("c1", "one"), _chunk("c4", "four")], max_chars=100)

    assert out[0]["context_text"] == "one\ntwo\nfour"
    assert "context_text" not in out[1]


def test_lookup_failure_falls_back_to_child_text(monkeypatch):
    def boom(db, ids):
        raise RuntimeError("db down")

    monkeypatch.setattr(pc, "_sibling_rows", boom)
    chunks = [_chunk("c1", "one")]

    assert pc.attach_parent_context(None, chunks) is chunks


def test_build_context_prefers_context_text():
    from app.pipeline.tasks.chat import _build_context

    ctx = _build_context([
        {"filename": "a.pdf", "page_number": 3, "text": "hit", "context_text": "before\nhit"},
        {"filename": "b.pdf", "text": "plain"},
    ])

    assert ctx == "[1] a.pdf (3쪽): before\nhit\n\n[2] b.pdf: plain"


def test_with_parent_context_respects_collection_setting(monkeypatch):
    from app.pipeline.tasks import chat
    from app.services import search_settings

    calls = []
    monkeypatch.setattr(pc, "attach_parent_context", lambda db, chunks: calls.append(chunks) or chunks)
    monkeypatch.setattr(
        search_settings, "collection_search_settings_sync",
        lambda db, cid: search_settings.SearchSettings(parent_context=cid != "off"),
    )

    chat._with_parent_context(None, [_chunk("c1", "one")], "off")
    assert calls == []
    chat._with_parent_context(None, [_chunk("c1", "one")], "on")
    assert len(calls) == 1
