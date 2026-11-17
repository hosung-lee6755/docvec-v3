"""Docling 구조 블록 보정(structure_refine.py, 2026-11-13)."""
from app.pipeline.blocks.structure_refine import assign_tiers, estimate_font_size, refine_element_blocks


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
