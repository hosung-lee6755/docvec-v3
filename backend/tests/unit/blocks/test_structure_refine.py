"""Docling 구조 블록 보정(structure_refine.py, 2026-11-13)."""
from app.pipeline.blocks.structure_refine import (
    assign_measured_tiers,
    assign_tiers,
    estimate_font_size,
    refine_element_blocks,
)


def _el(eid, el_type, page, bbox, text=""):
    return {"id": eid, "type": el_type, "page": page, "bbox": bbox, "content": {"text": text}}


def _block(node_type, text, eid, page, level=None):
    return (node_type, level if level is not None else (1 if node_type == "HEADING" else None), 0, 1, text,
            {"page_number": page, "element_id": eid})


def test_font_estimate_cancels_line_count():
    one_line = estimate_font_size("가나다라", [0, 112, 48, 100])        # 높이 12, 글자당 12
    two_lines = estimate_font_size("가나다라마바사아", [0, 126, 48, 100])  # 두 줄: 높이 26, 너비는 같다
    assert round(one_line) == 12
    assert abs(two_lines - one_line) / one_line < 0.1


def test_assign_tiers_groups_close_sizes_and_caps_level():
    sizes = [56.0, 54.0, 14.4, 14.4, 14.0, 12.6, 10.8, 10.8, 9.9, 9.0]
    level_of = assign_tiers(sizes, max_level=3)
    assert level_of[56.0] == level_of[54.0] == 1
    assert level_of[14.4] == level_of[14.0] == 2
    assert level_of[10.8] == level_of[9.0] == 3
    assert max(level_of.values()) == 3
    ordered = [level_of[s] for s in sorted(set(sizes), reverse=True)]
    assert ordered == sorted(ordered)


def test_assign_tiers_merges_near_identical_clusters():
    assert set(assign_tiers([12.0, 12.2, 12.4, 11.9], max_level=3).values()) == {1}


def test_heading_levels_follow_font_size():
    elements = [
        _el("h1", "section_header", 1, [0, 714.4, 28, 700]),   # "소개" 14.4pt
        _el("h2", "section_header", 1, [0, 612.6, 50, 600]),   # "도입 배경" 약 12pt
        _el("p", "text", 1, [0, 500, 300, 400]),
    ]
    blocks = [
        _block("HEADING", "소개", "h1", 1),
        _block("HEADING", "도입 배경", "h2", 1),
        _block("PARAGRAPH", "본문", "p", 1),
    ]

    out = refine_element_blocks(blocks, elements)

    assert [b[1] for b in out] == [1, 2, None]
    assert blocks[1][1] == 1  # 입력은 그대로다


def test_uniform_heading_sizes_keep_docling_levels():
    elements = [_el("a", "section_header", 1, [0, 112, 24, 100]), _el("b", "section_header", 2, [0, 112, 24, 100])]
    out = refine_element_blocks([_block("HEADING", "가나", "a", 1), _block("HEADING", "다라", "b", 2)], elements)
    assert [b[1] for b in out] == [1, 1]


def test_toc_page_heading_repeated_later_becomes_toc():
    elements = [
        _el("toc", "document_index", 2, [0, 700, 400, 200]),
        _el("t1", "section_header", 2, [0, 512, 60, 500]),
        _el("t2", "section_header", 2, [0, 412, 60, 400]),
        _el("h", "section_header", 9, [0, 712, 60, 700]),
    ]
    blocks = [
        _block("TOC", "", "toc", 2),
        _block("HEADING", "Ⅳ. 컴포넌트", "t1", 2),
        _block("HEADING", "목차", "t2", 2),
        _block("HEADING", "Ⅳ.  컴포넌트", "h", 9),
    ]

    out = refine_element_blocks(blocks, elements)

    assert [b[0] for b in out] == ["TOC", "TOC", "HEADING", "HEADING"]


def test_repeated_edge_text_becomes_header_but_body_labels_stay():
    elements, blocks = [], []
    for page in (1, 2, 3):
        elements += [
            _el(f"hd{page}", "text", page, [0, 830, 300, 820]),
            _el(f"lb{page}", "section_header", page, [0, 500, 60, 490]),
            _el(f"ft{page}", "text", page, [0, 22, 20, 10]),
        ]
        blocks += [
            _block("PARAGRAPH", "가이드라인 | Ⅰ. 소개", f"hd{page}", page),
            _block("HEADING", "[모범 사례]", f"lb{page}", page),
            _block("PARAGRAPH", str(page + 10), f"ft{page}", page),
        ]

    out = refine_element_blocks(blocks, elements)

    assert [b[0] for b in out[:3]] == ["HEADER", "HEADING", "FOOTER"]


def test_single_character_paragraph_noise_is_dropped():
    elements = [_el("n", "text", 1, [0, 30, 5, 25]), _el("p", "text", 1, [0, 500, 300, 400])]
    out = refine_element_blocks([_block("PARAGRAPH", "㔕", "n", 1), _block("PARAGRAPH", "본문", "p", 1)], elements)
    assert [b[4] for b in out] == ["본문"]


def test_toc_page_paragraph_matching_a_heading_becomes_toc():
    elements = [
        _el("toc", "document_index", 4, [0, 700, 400, 200]),
        _el("p", "text", 4, [0, 219, 90, 203]),
        _el("h", "section_header", 30, [0, 712, 60, 700]),
    ]
    blocks = [_block("TOC", "", "toc", 4), _block("PARAGRAPH", "Ⅴ. 기본 패턴", "p", 4), _block("HEADING", "Ⅴ. 기본 패턴", "h", 30)]

    out = refine_element_blocks(blocks, elements)

    assert [b[0] for b in out] == ["TOC", "TOC", "HEADING"]


def test_real_font_sizes_put_box_heading_under_the_chapter_heading():
    # bbox 어림으로는 "□ 사업 개요"가 "1. 사업 개요"보다 크게 잡히지만 실제 글자 크기는 둘 다 10.7pt 다(2026-11-20)
    elements = [
        _el("h0", "section_header", 1, [0, 730, 200, 700]),    # 큰 표지 제목
        _el("h1", "section_header", 1, [0, 611, 66, 600]),     # "1. 사업 개요"
        _el("h2", "section_header", 1, [0, 513, 78, 500]),     # "□ 사업 개요" (어림값이 더 크다)
        _el("h3", "section_header", 1, [0, 411, 66, 400]),     # "2. 신청 방법"
    ]
    blocks = [
        _block("HEADING", "2026년도 공고", "h0", 1),
        _block("HEADING", "1. 사업 개요", "h1", 1),
        _block("HEADING", "□ 사업 개요", "h2", 1),
        _block("HEADING", "2. 신청 방법", "h3", 1),
    ]
    sizes = {"h0": 20.0, "h1": 10.7, "h2": 10.7, "h3": 10.7}

    out = refine_element_blocks(blocks, elements, font_sizes=sizes)

    levels = [b[1] for b in out]
    assert levels[2] == levels[1] + 1
    assert levels[3] == levels[1]


def test_marker_order_keeps_a_larger_box_heading_at_its_own_level():
    elements = [_el(e, "section_header", 1, [0, 100, 10, 90]) for e in ("a", "b", "c")]
    blocks = [
        _block("HEADING", "1. 개요", "a", 1),
        _block("HEADING", "□ 큰 제목", "b", 1),
        _block("HEADING", "○ 세부", "c", 1),
    ]

    out = refine_element_blocks(blocks, elements, font_sizes={"a": 10.0, "b": 16.0, "c": 10.0})

    assert out[1][1] < out[0][1]          # □ 가 확실히 더 크면 기호 순서로 내리지 않는다
    assert out[2][1] == out[1][1] + 1     # ○ 는 □ 아래로 간다


def test_marker_order_does_not_touch_unmarked_or_sub_numbered_headings():
    elements = [_el(e, "section_header", 1, [0, 100, 10, 90]) for e in ("a", "b")]
    blocks = [_block("HEADING", "1. 개요", "a", 1), _block("HEADING", "1.1 범위", "b", 1)]
    out = refine_element_blocks(blocks, elements, font_sizes={"a": 10.0, "b": 10.0})
    assert [b[1] for b in out] == [1, 1]


def test_measured_tiers_ignore_one_off_cover_sizes():
    # Pub120bk(2026-11-20): 표지 32/24pt 가 한 번씩 나와도 본문 제목층 18/12/10pt 가 1/2/3단계로 나뉜다
    sizes = [32.0, 32.0, 24.0] + [18.0] * 49 + [15.0] * 2 + [12.0] * 900 + [10.0] * 950
    level_of = assign_measured_tiers(sizes, max_level=3)
    assert (level_of[18.0], level_of[12.0], level_of[10.0]) == (1, 2, 3)
    assert level_of[32.0] == level_of[24.0] == 1


def test_consecutive_chapter_numbers_share_a_level_despite_a_small_size_drop():
    # 자율형공장 공고문(2026-11-20): 1~6장은 16pt, 7장은 15pt 라 7장이 6장 아래로 들어갔다
    elements = [_el(e, "section_header", 1, [0, 100, 10, 90]) for e in ("a", "b", "c", "d")]
    blocks = [
        _block("HEADING", "6. 유의 사항", "a", 1),
        _block("HEADING", "□ 교육 이수", "b", 1),
        _block("HEADING", "7. 추진근거", "c", 1),
        _block("HEADING", "□ 근거 법령", "d", 1),
    ]
    sizes = {"a": 16.0, "b": 14.0, "c": 15.0, "d": 14.0}

    out = refine_element_blocks(blocks, elements, font_sizes=sizes)

    assert out[2][1] == out[0][1]
    assert out[3][1] > out[2][1]


def test_chapter_number_after_a_clearly_smaller_numbered_item_keeps_its_own_level():
    elements = [_el(e, "section_header", 1, [0, 100, 10, 90]) for e in ("a", "b", "c")]
    blocks = [
        _block("HEADING", "1. 개요", "a", 1),
        _block("HEADING", "1. 세부 항목", "b", 1),
        _block("HEADING", "2. 신청 방법", "c", 1),
    ]
    out = refine_element_blocks(blocks, elements, font_sizes={"a": 16.0, "b": 11.0, "c": 16.0})
    assert out[2][1] == out[0][1] < out[1][1]
