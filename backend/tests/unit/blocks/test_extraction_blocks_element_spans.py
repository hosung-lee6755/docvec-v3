from app.pipeline.adapters.base import RawPage, RawTextBlock
from app.pipeline.blocks.extraction_blocks import _assemble_full_text


def _page(page_number, *blocks):
    return RawPage(
        page_number=page_number, width=595, height=842,
        text_blocks=list(blocks), table_candidates=[], image_regions=[],
    )


def test_spans_point_at_the_exact_substring_in_full_text():
    pages = [
        _page(1, RawTextBlock(text="첫 문단입니다.", page_number=1, element_id="el-1")),
        _page(1, RawTextBlock(text="두 번째 문단입니다.", page_number=1, element_id="el-2")),
    ]

    full_text, spans = _assemble_full_text(pages, set())

    for element_id, (start, end) in spans.items():
        block_text = next(
            b.text for p in pages for b in p.text_blocks if b.element_id == element_id
        )
        assert full_text[start:end] == block_text


def test_blocks_without_element_id_get_no_span_entry():
    pages = [_page(1, RawTextBlock(text="레거시 어댑터 문단.", page_number=1))]

    full_text, spans = _assemble_full_text(pages, set())

    assert full_text == "레거시 어댑터 문단."
    assert spans == {}


def test_excluded_repeated_header_line_has_no_span_and_is_stripped_from_text():
    pages = [
        _page(
            1,
            RawTextBlock(text="회사명 기밀문서", page_number=1, element_id="header-1"),
            RawTextBlock(text="본문 내용.", page_number=1, element_id="body-1"),
        ),
    ]

    full_text, spans = _assemble_full_text(pages, {"회사명 기밀문서"})

    assert full_text == "본문 내용."
    assert "header-1" not in spans
    start, end = spans["body-1"]
    assert full_text[start:end] == "본문 내용."


def test_join_separator_is_accounted_for_in_offsets():
    pages = [
        _page(1, RawTextBlock(text="A", page_number=1, element_id="a")),
        _page(1, RawTextBlock(text="B", page_number=1, element_id="b")),
    ]

    full_text, spans = _assemble_full_text(pages, set())

    assert full_text == "A\n\nB"
    assert spans["a"] == (0, 1)
    assert spans["b"] == (3, 4)


def test_table_block_text_gets_a_span_like_any_other_block():
    # 문서 파싱 고도화 Phase 2 — 표 markdown도 다른 요소처럼 text_blocks에
    # 남으므로(docling_adapter.py), 여기서도 동일하게 span이 계산돼야 표가
    # elements 트리 구성에서 누락되지 않는다.
    pages = [
        _page(
            1,
            RawTextBlock(text="본문.", page_number=1, element_id="p-1"),
            RawTextBlock(text="| a | b |\n|---|---|\n| 1 | 2 |", page_number=1, element_id="table-1", block_type="table"),
        ),
    ]

    full_text, spans = _assemble_full_text(pages, set())

    start, end = spans["table-1"]
    assert full_text[start:end] == "| a | b |\n|---|---|\n| 1 | 2 |"
