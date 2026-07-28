from app.pipeline.blocks.structure_blocks import _extract_title


def test_first_heading_becomes_title():
    built_blocks = [
        ("TOC", None, 0, 10, "목차", None),
        ("PARAGRAPH", None, 10, 20, "서문입니다.", None),
        ("HEADING", 1, 20, 30, "1. 개요", None),
        ("HEADING", 2, 30, 40, "1.1 목적", None),
    ]

    assert _extract_title(built_blocks) == "1. 개요"


def test_no_heading_returns_none():
    built_blocks = [
        ("PARAGRAPH", None, 0, 10, "제목 없는 문서 본문.", None),
    ]

    assert _extract_title(built_blocks) is None


def test_empty_heading_text_is_skipped_in_favor_of_next_heading():
    built_blocks = [
        ("HEADING", 1, 0, 0, "", None),
        ("HEADING", 1, 5, 15, "실제 제목", None),
    ]

    assert _extract_title(built_blocks) == "실제 제목"


def test_title_truncated_to_500_chars():
    long_heading = "가" * 600
    built_blocks = [("HEADING", 1, 0, 600, long_heading, None)]

    result = _extract_title(built_blocks)

    assert result == "가" * 500
