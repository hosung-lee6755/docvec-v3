"""인용 위치 보기(쪽 그림이 없는 형식): 청크 둘레의 글을 잘라 돌려주는 순수 함수."""
from types import SimpleNamespace

from app.services import citation_context as cc


def _chunk(**kwargs):
    base = {"span_start": None, "span_end": None, "chunk_text": "", "original_text": None}
    return SimpleNamespace(**{**base, **kwargs})


TEXT = "앞 문단입니다. " * 5 + "인용된 본문 문장입니다." + " 뒤 문단입니다." * 5


def _span():
    start = TEXT.index("인용된")
    return start, start + len("인용된 본문 문장입니다.")


def test_uses_span_when_the_text_there_matches_the_chunk():
    start, end = _span()

    result = cc.build_context(TEXT, _chunk(span_start=start, span_end=end, original_text=TEXT[start:end], chunk_text="x"))

    assert result["located"] is True
    assert result["text"] == "인용된 본문 문장입니다."
    assert result["before"].endswith("앞 문단입니다. ") and result["after"].startswith(" 뒤 문단입니다.")


def test_window_is_capped_and_reports_that_more_text_exists():
    text = "가" * 1000 + "대상 문장" + "나" * 1000
    start = 1000

    result = cc.build_context(text, _chunk(span_start=start, span_end=start + 5, original_text="대상 문장"), window=100)

    assert len(result["before"]) == 100 and len(result["after"]) == 100
    assert result["has_more_before"] is True and result["has_more_after"] is True


def test_window_at_document_edges_has_no_more_text():
    result = cc.build_context("처음 문장 끝", _chunk(span_start=0, span_end=2, original_text="처음"))

    assert result["before"] == "" and result["has_more_before"] is False
    assert result["after"] == " 문장 끝" and result["has_more_after"] is False


def test_falls_back_to_searching_the_chunk_text_when_span_is_stale():
    # 청크 수정이나 재처리로 위치가 어긋난 경우
    result = cc.build_context(TEXT, _chunk(span_start=0, span_end=5, original_text="없는 글", chunk_text="인용된 본문 문장입니다."))

    assert result["located"] is True and result["text"] == "인용된 본문 문장입니다."


def test_searches_original_text_before_chunk_text_and_handles_missing_span():
    result = cc.build_context(TEXT, _chunk(original_text="인용된 본문", chunk_text="[절 머리말]\n인용된 본문"))

    assert result["located"] is True and result["text"] == "인용된 본문"


def test_unlocated_returns_only_the_chunk_text_never_other_text():
    result = cc.build_context(TEXT, _chunk(chunk_text="원문 어디에도 없는 글"))

    assert result == {
        "located": False, "before": "", "text": "원문 어디에도 없는 글", "after": "",
        "has_more_before": False, "has_more_after": False,
    }


def test_no_document_text_is_unlocated():
    for empty in (None, ""):
        result = cc.build_context(empty, _chunk(span_start=0, span_end=3, chunk_text="본문"))
        assert result["located"] is False and result["text"] == "본문" and result["before"] == ""


def test_invalid_span_values_are_ignored():
    for start, end in ((-5, 3), (10, 5), (0, 10**9), (None, 4)):
        result = cc.build_context("짧은 글", _chunk(span_start=start, span_end=end, chunk_text="짧은"))
        assert result["located"] is True and result["text"] == "짧은"


def test_whitespace_only_chunk_is_not_searched():
    result = cc.build_context("a b c", _chunk(chunk_text="   "))

    assert result["located"] is False
