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


def _same_size_blocks(texts):
    ids = [f"h{i}" for i in range(len(texts))]
    elements = [_el(e, "section_header", 1, [0, 100, 10, 90]) for e in ids]
    blocks = [_block("HEADING", t, e, 1) for t, e in zip(texts, ids)]
    return blocks, elements, ids


def test_decimal_numbering_depth_sets_levels_when_sizes_are_equal():
    # KRS SG 0027(2026-11-20): 표지 글자가 1·2단계를 차지해 "3.", "3.2", "3.2.1"이 모두 3단계로 평평했다
    texts = ["한국철도표준규격", "MJ81 형 선로전환기", "1.  적용범위 및 분류", "1.1  적용범위", "1.2  분류",
             "3.  필요조건", "3.2  형태", "3.2.1 일반구조", "3.2.2 외함", "4.  검사 및 시험"]
    blocks, elements, ids = _same_size_blocks(texts)
    sizes = dict(zip(ids, [36.0, 15.9, 10, 10, 10, 10, 10, 10, 10, 10]))

    out = refine_element_blocks(blocks, elements, font_sizes=sizes)

    level = {b[4]: b[1] for b in out}
    assert level["1.  적용범위 및 분류"] == level["3.  필요조건"] == level["4.  검사 및 시험"] == 1
    assert level["1.1  적용범위"] == level["3.2  형태"] == 2
    assert level["3.2.1 일반구조"] == level["3.2.2 외함"] == 3


def test_decimal_depth_keeps_chapters_below_a_title_when_there_is_room():
    texts = ["사업 안내서", "1. 개요", "1.1 목적", "1.2 범위", "2. 절차"]
    blocks, elements, ids = _same_size_blocks(texts)
    sizes = dict(zip(ids, [20.0, 14.0, 12.0, 12.0, 14.0]))

    out = refine_element_blocks(blocks, elements, font_sizes=sizes)

    assert [b[1] for b in out] == [1, 2, 3, 3, 2]


def test_decimal_depth_ignores_dates_amounts_and_documents_without_sub_numbers():
    texts = ["1. 사업 개요", "2026.4.17 공고", "0.5 mm 이하", "2. 신청 방법"]
    blocks, elements, ids = _same_size_blocks(texts)
    out = refine_element_blocks(blocks, elements, font_sizes=dict.fromkeys(ids, 12.0))
    assert [b[1] for b in out] == [1, 1, 1, 1]


def test_childless_first_chapter_follows_the_next_numbered_chapter():
    # KR S-03010: 첫 장 "1. 용어의 정의"는 하위 절이 없어 다음 장과 단계가 어긋났다
    texts = ["표지 제목", "1. 용어의 정의", "2. 일반사항", "2.1 개요", "2.2 구성", "3. 선정조건", "3.1 종류", "3.1.1 전기식"]
    blocks, elements, ids = _same_size_blocks(texts)
    sizes = dict(zip(ids, [30.0] + [10.0] * 7))

    out = refine_element_blocks(blocks, elements, font_sizes=sizes)

    level = {b[4]: b[1] for b in out}
    assert level["1. 용어의 정의"] == level["2. 일반사항"] == level["3. 선정조건"] == 1
    assert level["2.1 개요"] == level["3.1 종류"] == 2
    assert level["3.1.1 전기식"] == 3


def test_numbered_items_without_sub_numbers_inside_annexes_keep_their_level():
    # 기계설비 매뉴얼: 별표 속 "5. 문화 및 집회시설" 같은 항목은 하위 번호가 없어 장으로 올리지 않는다
    texts = ["2. 냉동기", "2.1 일반", "2.1.1 흡수식", "[별표 1] 건축물 용도", "5. 문화 및 집회시설", "6. 종교시설"]
    blocks, elements, ids = _same_size_blocks(texts)
    sizes = dict(zip(ids, [14.0, 12.0, 12.0, 14.0, 10.0, 10.0]))

    out = refine_element_blocks(blocks, elements, font_sizes=sizes)

    level = {b[4]: b[1] for b in out}
    assert (level["2. 냉동기"], level["2.1 일반"], level["2.1.1 흡수식"]) == (1, 2, 3)
    assert level["5. 문화 및 집회시설"] == level["6. 종교시설"] == 3


def test_numbered_chapters_nest_under_commentary_containers():
    # KR S-03010: "해설 2." 아래 "1. 전기식 선로전환기"가 해설보다 위로 올라가 해설 제목이 절 경로에서 빠졌다
    texts = ["1. 용어", "2. 일반사항", "2.1 개요", "2.1.1 구성", "해설 1. 일반사항", "1. 개요", "2. 결정",
             "해설 2. 종류", "1. 전기식", "1.1 NS형", "1.2 MJ81형", "2. 기계식"]
    blocks, elements, ids = _same_size_blocks(texts)

    out = refine_element_blocks(blocks, elements, font_sizes=dict.fromkeys(ids, 10.0))

    level = {b[4]: b[1] for b in out}
    assert level["2. 일반사항"] == 1 and level["2.1 개요"] == 2 and level["2.1.1 구성"] == 3
    assert level["해설 1. 일반사항"] == level["해설 2. 종류"] == 1
    assert level["1. 전기식"] == level["2. 기계식"] == level["1. 개요"] == 2
    assert level["1.1 NS형"] == 3


def test_fourth_number_depth_gets_its_own_level_when_max_level_is_five():
    # 상한 3일 때는 "해설 2. > 1. > 1.1 > 1.1.2"의 1.1.2가 1.1과 같은 3단계였다
    texts = ["1. 용어", "2. 일반사항", "2.1 개요", "2.1.1 구성", "해설 2. 종류", "1. 전기식", "1.1 NS형",
             "1.1.1 구조", "1.1.2 클러치", "2. 기계식"]
    blocks, elements, ids = _same_size_blocks(texts)

    out = refine_element_blocks(blocks, elements, max_level=5, font_sizes=dict.fromkeys(ids, 10.0))

    level = {b[4]: b[1] for b in out}
    assert level["2. 일반사항"] == 1 and level["2.1 개요"] == 2 and level["2.1.1 구성"] == 3
    assert level["해설 2. 종류"] == 1 and level["1. 전기식"] == 2 and level["1.1 NS형"] == 3
    assert level["1.1.1 구조"] == level["1.1.2 클러치"] == 4


def test_font_size_tiers_stay_at_three_when_max_level_is_five():
    # 상한을 5로 올리자 표지의 드문 큰 글자가 1·2단계를 차지해 장 제목이 3~4단계로 밀렸다(기계설비 매뉴얼)
    texts = ["표지 제목", "부제", "제1장 총칙", "제2장 설비", "가. 일반", "나. 기준", "다. 시험"]
    blocks, elements, ids = _same_size_blocks(texts)
    sizes = dict(zip(ids, [30.0, 20.0, 16.0, 16.0, 12.0, 12.0, 12.0]))

    three = {b[4]: b[1] for b in refine_element_blocks(blocks, elements, max_level=3, font_sizes=sizes)}
    five = {b[4]: b[1] for b in refine_element_blocks(blocks, elements, max_level=5, font_sizes=sizes)}

    assert five == three


def test_korean_letter_and_paren_number_headings_nest_under_numbered_heading():
    # 세원화성 에너지진단보고서(2026-11-20): "2. 에너지 사용현황", "가. 에너지원별 사용량", "(1) 수전현황"이
    # 같은 크기라 모두 같은 단계가 되어 "2." 제목이 절 경로에서 빠지고 본문 없는 짧은 청크로 남았다
    ids = ("r", "n2", "ga", "na", "p1", "p2", "n3")
    elements = [_el(e, "section_header", 1, [0, 100, 10, 90]) for e in ids]
    blocks = [
        _block("HEADING", "Ⅰ. 일반현황", "r", 1),
        _block("HEADING", "2. 에너지 사용현황", "n2", 1),
        _block("HEADING", "가. 에너지원별 사용량", "ga", 1),
        _block("HEADING", "나. 전력 사용 현황", "na", 1),
        _block("HEADING", "(1) 수전현황", "p1", 1),
        _block("HEADING", "1) 월평균 전력사용량", "p2", 1),
        _block("HEADING", "3. 온실가스 배출량 현황", "n3", 1),
    ]
    sizes = {"r": 16.0, "n2": 12.0, "ga": 12.0, "na": 12.0, "p1": 12.0, "p2": 12.0, "n3": 12.0}

    out = refine_element_blocks(blocks, elements, max_level=5, font_sizes=sizes)

    level = {e: b[1] for e, b in zip(ids, out)}
    assert level["ga"] == level["na"] == level["n2"] + 1
    assert level["p1"] == level["p2"] == level["na"] + 1
    assert level["n3"] == level["n2"]


def test_part_divider_and_its_title_become_one_chapter_heading():
    # 경기도 데이터분석 사례집(2026-11-20): 장 구분 쪽의 "PART 01"과 "분석개요"가 일반 글이라 장 제목이 없었다
    elements = [_el(e, "text", p, [0, 100, 10, 90]) for e, p in (("p1", 4), ("t1", 4), ("b1", 5), ("p3", 8))]
    elements.append(_el("h3", "section_header", 8, [0, 100, 10, 90]))
    blocks = [
        ("PARAGRAPH", None, 10, 17, "PART 01", {"page_number": 4, "element_id": "p1"}),
        ("PARAGRAPH", None, 19, 23, "분석개요", {"page_number": 4, "element_id": "t1"}),
        ("PARAGRAPH", None, 25, 60, "본문 문단은 그대로 둔다. 충분히 긴 설명 문장입니다.", {"page_number": 5, "element_id": "b1"}),
        ("PARAGRAPH", None, 62, 69, "PART 03", {"page_number": 8, "element_id": "p3"}),
        ("HEADING", 2, 71, 75, "분석결과", {"page_number": 8, "element_id": "h3"}),
    ]

    out = refine_element_blocks(blocks, elements)

    assert [(b[0], b[1], b[2], b[3], b[4]) for b in out] == [
        ("HEADING", 1, 10, 23, "PART 01 분석개요"),
        ("PARAGRAPH", None, 25, 60, "본문 문단은 그대로 둔다. 충분히 긴 설명 문장입니다."),
        ("HEADING", 1, 62, 75, "PART 03 분석결과"),
    ]


def test_part_line_without_a_title_on_the_same_page_becomes_a_heading_alone():
    elements = [_el("p1", "text", 4, [0, 100, 10, 90]), _el("b1", "text", 5, [0, 100, 10, 90])]
    blocks = [
        ("PARAGRAPH", None, 0, 6, "PART 2", {"page_number": 4, "element_id": "p1"}),
        ("PARAGRAPH", None, 8, 14, "다음 쪽 본문", {"page_number": 5, "element_id": "b1"}),
    ]

    out = refine_element_blocks(blocks, elements)

    assert (out[0][0], out[0][1], out[0][4]) == ("HEADING", 1, "PART 2")
    assert out[1][0] == "PARAGRAPH"
