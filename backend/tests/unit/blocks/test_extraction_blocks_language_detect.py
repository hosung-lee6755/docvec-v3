from app.pipeline.blocks.extraction_blocks import _detect_language


def test_dominant_hangul_text_detected_as_ko():
    text = "이것은 한글로 작성된 문서입니다. 페이지 전체가 한글 문장으로 구성되어 있습니다."

    assert _detect_language(text) == "ko"


def test_dominant_latin_text_detected_as_en():
    text = "This document is written entirely in English prose across the page."

    assert _detect_language(text) == "en"


def test_empty_text_returns_none():
    assert _detect_language("") is None


def test_no_hangul_or_latin_characters_returns_none():
    assert _detect_language("123 456 789 !@# %^&") is None


def test_roughly_balanced_mix_returns_none():
    text = "가나다라마 abcde"

    assert _detect_language(text) is None
