from app.pipeline.blocks.structure_blocks import (
    _build_blocks,
    _classify,
    _detect_toc_line_offsets,
    _resolve_source_table_id,
)


def _line(text, font_size=11.0, is_bold=False, page_number=1, role=None):
    return {
        "text": text, "font_size": font_size, "is_bold": is_bold,
        "is_italic": False, "page_number": page_number, "role": role,
    }


def test_bold_oversized_line_without_numbering_is_promoted_to_heading():
    text = (
        "Body one.\n"
        "A Big Bold Heading Without Numbering\n"
        "Body two continues here."
    )
    layout = [
        _line("Body one."),
        _line("A Big Bold Heading Without Numbering", font_size=16.0, is_bold=True),
        _line("Body two continues here."),
    ]

    blocks = _build_blocks(text, layout)

    heading = next(b for b in blocks if b[0] == "HEADING")
    assert heading[4] == "A Big Bold Heading Without Numbering"
    assert heading[1] == 1
    assert heading[5]["font_size"] == 16.0


def test_small_font_delta_does_not_trigger_false_heading():
    # Rendering jitter (11.0 vs 12.0, below _HEADING_FONT_DELTA) must not be
    # mistaken for a real heading promotion.
    text = "Body one.\nBody two, slightly larger but not a heading.\nBody three."
    layout = [
        _line("Body one."),
        _line("Body two, slightly larger but not a heading.", font_size=12.0, is_bold=True),
        _line("Body three."),
    ]

    blocks = _build_blocks(text, layout)

    assert all(b[0] != "HEADING" for b in blocks)


def test_regex_heading_wins_over_absent_font_signal():
    node_type, level = _classify("1. 서론", layout=None, body_font_size=None)
    assert (node_type, level) == ("HEADING", 1)


def test_footnote_role_becomes_footnote_node_even_when_regex_would_match_list():
    # "1) ..." also matches the numbered-heading/list regexes — the footnote
    # role (already established via bottom-zone position in Phase 1) must
    # win so footnotes don't get folded into headings or list items.
    text = "Body paragraph.\n1) 이것은 각주 설명입니다.\nMore body text."
    layout = [
        _line("Body paragraph."),
        _line("1) 이것은 각주 설명입니다.", role="footnote"),
        _line("More body text."),
    ]

    blocks = _build_blocks(text, layout)

    footnote = next(b for b in blocks if b[0] == "FOOTNOTE")
    assert footnote[4] == "1) 이것은 각주 설명입니다."


def test_toc_offsets_detected_for_dot_leader_page_number_run():
    text = (
        "1장 서론 ..................... 3\n"
        "2장 배경 ..................... 8\n"
        "3장 방법론 ................... 15\n"
        "\n"
        "본문이 여기서 시작됩니다."
    )

    offsets = _detect_toc_line_offsets(text)

    assert len(offsets) == 3


def test_toc_run_below_minimum_is_not_detected():
    text = "1장 서론 ..................... 3\n2장 배경 ..................... 8\n본문 시작."

    offsets = _detect_toc_line_offsets(text)

    assert offsets == set()


def test_toc_lines_override_numbered_heading_classification():
    text = (
        "1장 서론 ..................... 3\n"
        "2장 배경 ..................... 8\n"
        "3장 방법론 ................... 15\n"
    )
    toc_offsets = _detect_toc_line_offsets(text)

    blocks = _build_blocks(text, layout_entries=None, toc_offsets=toc_offsets)

    assert all(b[0] == "TOC" for b in blocks)


def test_resolve_source_table_id_matches_marker_number_to_tables_index():
    tables = [
        {"id": "table-a", "page_number": 1, "rows": []},
        {"id": "table-b", "page_number": 2, "rows": []},
    ]

    assert _resolve_source_table_id("[표 1]\n셀1 | 셀2", tables) == "table-a"
    assert _resolve_source_table_id("[표 2]\n셀1 | 셀2", tables) == "table-b"


def test_resolve_source_table_id_returns_none_when_marker_missing():
    assert _resolve_source_table_id("번호 없는 본문 문단입니다.", [{"id": "table-a"}]) is None


def test_resolve_source_table_id_returns_none_when_index_out_of_range():
    # A document reprocessed with fewer tables than a stale marker implies —
    # must not raise or silently wrap around to an unrelated table.
    assert _resolve_source_table_id("[표 5]\n셀1 | 셀2", [{"id": "table-a"}]) is None


def test_resolve_source_table_id_returns_none_when_tables_absent():
    assert _resolve_source_table_id("[표 1]\n셀1 | 셀2", None) is None


def test_fallback_matches_pre_phase2_output_when_extraction_layout_absent():
    # Regression: with no layout_entries and no toc_offsets, output must be
    # identical in shape to the pre-Phase-2 regex-only path.
    text = "1. 서론\n번호 없는 본문 문단입니다.\n\n- 목록 항목 하나"

    blocks = _build_blocks(text)

    types = [b[0] for b in blocks]
    assert types == ["HEADING", "PARAGRAPH", "LIST_ITEM"]
    assert all(b[5] is None for b in blocks if b[0] == "PARAGRAPH")
