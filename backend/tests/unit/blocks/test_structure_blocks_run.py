"""structure_blocks: StructureAnalyzeBlock.run 및 TOC/레이아웃 헬퍼 테스트 (DB 모킹)."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.pipeline.blocks import structure_blocks as sb
from app.pipeline.blocks.base import BlockContext

TEXT = "1. 서론\n본문 첫 줄\n본문 둘째 줄\n\n1.1 배경\n- 항목\n\n[표 1]\na | b\n1 | 2"


def _ctx(text=TEXT, config=None, extra=None, document_id="doc-1"):
    return BlockContext(
        run_id="r1", block_instance_id="b", document_id=document_id,
        upstream_outputs={"up": {"text": text, **(extra or {})}}, config=config or {},
    )


def _doc(**kw):
    base = dict(id="doc-1", extraction_layout=None, elements=None, tables=None, title=None)
    base.update(kw)
    return SimpleNamespace(**base)


def _run(doc, text=TEXT, config=None, extra=None):
    db = MagicMock()
    db.get.return_value = doc
    with patch("app.db.session.get_sync_db", return_value=db):
        result = sb.StructureAnalyzeBlock().run(_ctx(text, config, extra))
    nodes = [c.args[0] for c in db.add.call_args_list]
    return result, db, nodes


def _types(nodes):
    return [n.node_type for n in nodes]


# ---- 헬퍼 ----
def test_detect_toc_requires_min_run():
    toc = "1장 서론 ..... 3\n2장 본론 ..... 7\n3장 결론 ..... 9\n본문 시작"
    assert sb._detect_toc_line_offsets(toc) == {0, len("1장 서론 ..... 3\n"), len("1장 서론 ..... 3\n2장 본론 ..... 7\n")}
    assert sb._detect_toc_line_offsets("1장 서론 ..... 3\n2장 본론 ..... 7\n본문") == set()


def test_detect_toc_run_ended_by_blank_line_and_end_of_text():
    assert len(sb._detect_toc_line_offsets("가가 ..... 1\n나나 ..... 2\n다다 ..... 3\n\n본문")) == 3
    assert len(sb._detect_toc_line_offsets("가가 ..... 1\n나나 ..... 2\n다다 ..... 3")) == 3


def test_detect_toc_ignores_entries_beyond_search_window():
    filler = "\n".join(f"일반 문장 {i}" for i in range(sb._TOC_SEARCH_WINDOW + 1))
    toc = "\n".join(f"항목{i} ..... {i}" for i in range(3))
    assert sb._detect_toc_line_offsets(filler + "\n" + toc) == set()


def test_layout_cursor_matches_in_order_within_lookahead():
    entries = [{"text": "a"}, {"text": " b "}, {"text": "c"}]
    cursor = sb._LineLayoutCursor(entries)
    assert cursor.match("") is None
    assert cursor.match("b") is entries[1]
    assert cursor.match("a") is None  # 이미 지나간 항목
    assert cursor.match("c") is entries[2]
    assert cursor.match("zzz") is None


def test_layout_cursor_splits_multiline_entries_so_alignment_survives():
    # HTML 의 한 블록이 여러 줄을 담은 글꼴 항목으로 오는 경우(고도화보고서 실측, 2026-11-19).
    # 줄마다 나눠 짝짓지 않으면 앞쪽 몇 줄만 보다 짝을 잃고, 뒤의 큰 글씨 제목이 모두 문단이 된다.
    entries = [
        {"text": "차이가 생기는 이유\n본문 설명 한 줄\n또 한 줄", "font_size": 11.0},
        *({"text": f"문단 {i}", "font_size": 11.0} for i in range(8)),
        {"text": "부록 A. 용어", "font_size": 22.0, "is_bold": True},
    ]
    cursor = sb._LineLayoutCursor(entries)
    for line in ["차이가 생기는 이유", "본문 설명 한 줄", "또 한 줄", *(f"문단 {i}" for i in range(8))]:
        assert cursor.match(line) is not None
    matched = cursor.match("부록 A. 용어")
    assert matched is not None and matched["font_size"] == 22.0


def test_build_blocks_keeps_large_bold_heading_after_multiline_layout_entry():
    # 실측처럼 여러 줄 항목이 연달아 와서, 다음 한 줄 항목이 앞쪽 5개 범위 밖으로 밀리는 경우
    groups = [[f"설명 {g} 제목", f"설명 {g} 본문입니다."] for g in range(6)]
    explain = [line for group in groups for line in group]
    entries = [
        *({"text": "\n".join(group), "font_size": 11.0} for group in groups),
        *({"text": f"본문 문장 {i}입니다.", "font_size": 11.0} for i in range(8)),
        {"text": "부록 A. 용어", "font_size": 22.0, "is_bold": True},
        {"text": "용어 설명 본문입니다.", "font_size": 11.0},
    ]
    text = "\n".join(
        [*explain, *(f"본문 문장 {i}입니다." for i in range(8)), "", "부록 A. 용어", "용어 설명 본문입니다."]
    )
    blocks = sb._build_blocks(text, entries)
    headings = [b[4] for b in blocks if b[0] == "HEADING"]
    assert headings == ["부록 A. 용어"]


def test_build_blocks_nests_font_only_headings_under_larger_preceding_heading():
    # HTML 의 h2/h3/h4 는 글자 크기 22/20/18 로 옮겨 온다(simple_layout). 번호 없는 제목을 모두 수준 1로 두면
    # 번호 제목 "2.3 …" 아래의 h4 소제목이 최상위로 빠져 청크의 섹션 경로가 끊긴다(고도화보고서 실측, 2026-11-19).
    def head(text, size):
        return {"text": text, "font_size": size, "is_bold": True}

    def body(text):
        return {"text": text, "font_size": 11.0}

    entries = [
        head("2 다섯 가지 방안", 22.0), head("2.3 모델 구조", 20.0), head("운전성향 유형(D2)", 18.0),
        body("본문입니다."), head("2.3.1 학습 과정", 18.0), head("세부 항목", 16.0), body("본문입니다."),
        head("부록 C. 설정", 22.0), head("C.1 설정 테이블", 20.0), head("cfg_event_catalog", 18.0), body("본문입니다."),
    ]
    text = "\n".join(e["text"] for e in entries)
    headings = [(b[4], b[1]) for b in sb._build_blocks(text, entries, max_level=3) if b[0] == "HEADING"]
    assert headings == [
        ("2 다섯 가지 방안", 1), ("2.3 모델 구조", 2), ("운전성향 유형(D2)", 3),
        ("2.3.1 학습 과정", 3), ("세부 항목", 3),
        ("부록 C. 설정", 1), ("C.1 설정 테이블", 2), ("cfg_event_catalog", 3),
    ]


def test_build_blocks_gives_unnumbered_heading_the_level_of_same_size_numbered_heading():
    # 완료보고서: h1 문서 제목 뒤의 h2 "완료 결과 요약"과 h2 "1 사업 개요"는 같은 수준이어야 한다(2026-11-19)
    entries = [
        {"text": "완료 보고서", "font_size": 24.0, "is_bold": True},
        {"text": "완료 결과 요약", "font_size": 22.0, "is_bold": True},
        *({"text": f"본문 {i}입니다.", "font_size": 11.0} for i in range(4)),
        {"text": "1 사업 개요", "font_size": 22.0, "is_bold": True},
        {"text": "1-1 추진 배경", "font_size": 20.0, "is_bold": True},
        # 같은 20pt 에 수준이 엇갈리는 번호 제목이 있으면 20pt 는 기준으로 쓰지 않는다
        {"text": "1. 목록형 알림", "font_size": 18.0, "is_bold": True},
        {"text": "2.3.1 세부 절", "font_size": 18.0, "is_bold": True},
        {"text": "세부 소제목", "font_size": 18.0, "is_bold": True},
    ]
    text = "\n".join(e["text"] for e in entries)
    headings = [(b[4], b[1]) for b in sb._build_blocks(text, entries, max_level=3, markup_headings=True) if b[0] == "HEADING"]
    assert headings == [
        ("완료 보고서", 1), ("완료 결과 요약", 1), ("1 사업 개요", 1), ("1-1 추진 배경", 2),
        # 장 제목(22pt)보다 작은 "1. …"은 번호가 1단계여도 앞선 더 큰 제목 아래에 둔다
        ("1. 목록형 알림", 3), ("2.3.1 세부 절", 3), ("세부 소제목", 3),
    ]


def test_build_blocks_markup_format_ignores_numbered_body_lines_and_nests_small_numbered_headings():
    # HTML: 제목은 태그로 표시된다. 본문 글씨의 "01 … 적습니다." 문장은 제목이 아니고, 절 안 h5 "1. … 알림"은
    # 장("7 운영")과 같은 수준이 아니라 그 아래다(고도화보고서 실측, 2026-11-19)
    entries = [
        {"text": "2 고도화 방안", "font_size": 22.0, "is_bold": True},
        {"text": "01 화면 관리 차량 수가 등록 대수보다 적습니다(회사 5).", "font_size": 11.0, "is_bold": False},
        *({"text": f"본문 {i}입니다.", "font_size": 11.0} for i in range(4)),
        {"text": "7 운영 준비", "font_size": 22.0, "is_bold": True},
        {"text": "7.3 알림과 대응", "font_size": 20.0, "is_bold": True},
        {"text": "1. 원천 테이블 구조 변경 알림", "font_size": 16.0, "is_bold": True},
    ]
    text = "\n".join(e["text"] for e in entries)
    headings = [(b[4], b[1]) for b in sb._build_blocks(text, entries, max_level=3, markup_headings=True) if b[0] == "HEADING"]
    assert headings == [("2 고도화 방안", 1), ("7 운영 준비", 1), ("7.3 알림과 대응", 2), ("1. 원천 테이블 구조 변경 알림", 3)]
    # 제목 태그가 없는 형식(PDF 등)에서는 지금처럼 번호 줄도 제목 후보로 둔다
    plain = [b[4] for b in sb._build_blocks(text, entries, max_level=3) if b[0] == "HEADING"]
    assert "01 화면 관리 차량 수가 등록 대수보다 적습니다(회사 5)." in plain


def test_resolve_source_table_id_edges():
    tables = [{"id": "t1"}, {"id": "t2"}]
    assert sb._resolve_source_table_id("[표 2]\n...", tables) == "t2"
    assert sb._resolve_source_table_id("[표 3]\n...", tables) is None
    assert sb._resolve_source_table_id("[표 0]", tables) is None
    assert sb._resolve_source_table_id("본문", tables) is None
    assert sb._resolve_source_table_id("[표 1]", None) is None


def test_body_font_size_mode():
    assert sb._body_font_size([]) is None
    assert sb._body_font_size([{"font_size": 10.04}, {"font_size": 10.0}, {"font_size": 20}, {}]) == 10.0


def test_classify_footnote_and_korean_clause_and_font_promotion():
    assert sb._classify("1) 각주", {"role": "footnote"}, None) == ("FOOTNOTE", None)
    assert sb._classify("제3장 총칙", None, None) == ("HEADING", 1)
    assert sb._classify("큰 글씨", {"is_bold": True, "font_size": 20}, 10) == ("HEADING", 1)
    assert sb._classify("중간 글씨", {"is_bold": True, "font_size": 12.5}, 10) == ("HEADING", 2)
    assert sb._classify("작은 글씨", {"is_bold": True, "font_size": 10.5}, 10) == ("PARAGRAPH", None)


def test_node_type_for_element_mapping():
    expected = {
        "document_index": "TOC", "title": "HEADING", "section-header": "HEADING", "table": "TABLE",
        "list-item": "LIST_ITEM", "figure": "IMAGE", "caption": "CAPTION", "footnote": "FOOTNOTE",
        "page-header": "HEADER", "page_footer": "FOOTER", "text": "PARAGRAPH", "": "PARAGRAPH",
    }
    for el_type, node_type in expected.items():
        assert sb._node_type_for_element(el_type) == node_type


def test_build_blocks_from_elements_skips_empty_text_but_keeps_structural():
    elements = [
        {"id": "a", "type": "text", "content": {"text": "  "}},
        {"id": "b", "type": "section_header", "content": {"text": "제목"}, "metadata": {"level": 2},
         "span_start": 0, "span_end": 2, "page": 3},
        {"id": "c", "type": "document_index", "content": {}},
        {"id": "d", "type": "table"},
    ]
    blocks = sb._build_blocks_from_elements(elements)
    assert [b[0] for b in blocks] == ["HEADING", "TOC", "TABLE"]
    assert blocks[0][1] == 2 and blocks[0][5]["page_number"] == 3 and blocks[0][5]["is_bold"] is True


def test_extract_title_first_heading_truncated():
    blocks = [("PARAGRAPH", None, 0, 1, "x", None), ("HEADING", 1, 0, 1, "  " + "가" * 600, None)]
    assert sb._extract_title(blocks) == "가" * 500
    assert sb._extract_title([("PARAGRAPH", None, 0, 1, "x", None)]) is None


# ---- run: legacy 경로 ----
def test_run_requires_document_id():
    with pytest.raises(ValueError):
        sb.StructureAnalyzeBlock().run(_ctx(document_id=None))


def test_run_missing_document_closes_db():
    db = MagicMock()
    db.get.return_value = None
    with patch("app.db.session.get_sync_db", return_value=db):
        with pytest.raises(ValueError, match="찾을 수 없"):
            sb.StructureAnalyzeBlock().run(_ctx())
    db.close.assert_called_once()


def test_run_builds_tree_with_headings_lists_tables():
    doc = _doc(tables=[{"id": "tbl-1"}])
    result, db, nodes = _run(doc)
    assert _types(nodes) == ["DOCUMENT", "HEADING", "PARAGRAPH", "HEADING", "LIST_ITEM", "TABLE"]
    root, h1, para, h2, item, table = nodes
    assert h1.parent_node_id == root.id and para.parent_node_id == h1.id
    assert h2.level == 2 and h2.parent_node_id == h1.id
    assert item.parent_node_id == h2.id
    assert table.source_table_id == "tbl-1"
    assert [n.sort_order for n in nodes] == list(range(6))
    # 장 제목("1. 서론")은 문서 제목이 아니다 — 표지 줄도 파일명도 없으면 비워 둔다(title_resolver).
    assert doc.title is None
    assert result.output["node_count"] == 6 and result.output["text"] == TEXT
    assert result.metrics == {"node_count": 6}
    db.commit.assert_called_once()
    db.close.assert_called_once()


def test_toc_title_heading_does_not_become_the_parent_of_the_body():
    # 2026-11-27: "목 차" 가 1단계 제목이 되어 뒤의 본문 제목이 모두 그 아래로 들어갔다(예방점검 가이드 청크 313개)
    text = "목   차\n◈ 예방점검 개요\n본문"
    elements = [
        {"id": "t", "type": "section_header", "content": {"text": "목   차"}, "metadata": {"level": 1},
         "span_start": 0, "span_end": 5, "page": 2},
        {"id": "h", "type": "section_header", "content": {"text": "◈ 예방점검 개요"}, "metadata": {"level": 2},
         "span_start": 6, "span_end": 15, "page": 3},
        {"id": "p", "type": "text", "content": {"text": "본문"}, "span_start": 16, "span_end": 18, "page": 3},
    ]
    _, _, nodes = _run(_doc(elements=elements), text=text)

    root = nodes[0]
    by_text = {n.text: n for n in nodes[1:]}
    assert by_text["목   차"].node_type == "TOC"
    assert by_text["◈ 예방점검 개요"].node_type == "HEADING"
    assert by_text["◈ 예방점검 개요"].parent_node_id == root.id


def test_is_toc_title_matches_a_whole_line_only():
    from app.pipeline.blocks.toc_detection import is_toc_title

    assert all(is_toc_title(t) for t in ["목   차", "[차례]", "CONTENTS", "Table of Contents", "< 목 차 >"])
    assert not any(is_toc_title(t) for t in ["사업 추진 목차", "목차 작성 기준", ""])


def test_run_deletes_previous_tree():
    _, db, _ = _run(_doc())
    db.query.return_value.filter.return_value.delete.assert_called_once()


def test_run_detect_headings_disabled_turns_headings_into_paragraphs():
    _, _, nodes = _run(_doc(), config={"detect_headings": False})
    assert "HEADING" not in _types(nodes)


def test_run_detect_lists_disabled():
    _, _, nodes = _run(_doc(), config={"detect_lists": False})
    assert "LIST_ITEM" not in _types(nodes)


def test_run_heading_max_level_demotes_deeper_headings():
    _, _, nodes = _run(_doc(), config={"heading_max_level": 1})
    assert _types(nodes).count("HEADING") == 1


def test_run_sibling_heading_pops_stack():
    text = "1. 하나\n\n2. 둘\n\n2.1 둘의 하위\n\n3. 셋"
    _, _, nodes = _run(_doc(), text=text)
    h = [n for n in nodes if n.node_type == "HEADING"]
    root = nodes[0]
    assert h[1].parent_node_id == root.id
    assert h[2].parent_node_id == h[1].id
    assert h[3].parent_node_id == root.id


def test_run_toc_lines_become_toc_nodes_and_can_be_disabled():
    text = "1장 서론 ..... 3\n2장 본론 ..... 7\n3장 결론 ..... 9\n\n본문 문단"
    _, _, nodes = _run(_doc(), text=text)
    assert _types(nodes).count("TOC") == 3
    _, _, off = _run(_doc(), text=text, config={"detect_toc": False})
    assert "TOC" not in _types(off)


def test_run_uses_font_layout_signals_and_skips_header_footer_roles():
    layout = [
        {"text": "머리글", "role": "header", "font_size": 10},
        {"text": "큰 제목", "font_size": 20, "is_bold": True, "page_number": 1, "style_name": "H", "font_name": "F"},
        {"text": "본문", "font_size": 10, "is_bold": False},
        {"text": "본문", "font_size": 10, "is_bold": False},
    ]
    _, _, nodes = _run(_doc(extraction_layout=layout), text="큰 제목\n\n본문")
    heading = nodes[1]
    assert heading.node_type == "HEADING"
    assert heading.style["font_name"] == "F" and heading.page_number == 1


def test_run_font_signals_ignored_when_disabled():
    layout = [{"text": "큰 제목", "font_size": 20, "is_bold": True}, {"text": "본문", "font_size": 10}]
    _, _, nodes = _run(_doc(extraction_layout=layout), text="큰 제목\n\n본문", config={"use_font_signals": False})
    assert "HEADING" not in _types(nodes)


def test_run_truncates_node_text_to_2000_chars():
    _, _, nodes = _run(_doc(), text="가" * 5000)
    assert len(nodes[1].text) == 2000


def test_run_without_headings_leaves_title_none():
    doc = _doc()
    _run(doc, text="그냥 본문 문장입니다")
    assert doc.title is None


def test_run_carries_upstream_keys():
    result, _, _ = _run(_doc(), extra={"keep": 1})
    assert result.output["keep"] == 1


# ---- run: Docling elements 경로 ----
def test_run_elements_path_uses_element_ids_and_toc_toggle():
    elements = [
        {"id": "h", "type": "title", "content": {"text": "문서 제목"}, "span_start": 0, "span_end": 5, "page": 1},
        {"id": "t", "type": "table", "content": {"text": "표"}, "span_start": 7, "span_end": 9, "page": 1},
        {"id": "toc", "type": "document_index", "content": {}, "span_start": None, "span_end": None},
    ]
    doc = _doc(elements=elements, tables=[{"id": "ignored"}])
    result, _, nodes = _run(doc, text="문서 제목\n\n표", config={"detect_toc": False})
    assert _types(nodes) == ["DOCUMENT", "HEADING", "TABLE", "PARAGRAPH"]
    assert nodes[2].source_table_id == "t"
    assert nodes[1].element_id == "h"
    assert doc.title == "문서 제목"


def test_run_elements_path_keeps_toc_when_enabled():
    elements = [{"id": "toc", "type": "document_index", "content": {}}]
    _, _, nodes = _run(_doc(elements=elements), text="x")
    assert _types(nodes) == ["DOCUMENT", "TOC"]


def test_block_metadata():
    block = sb.StructureAnalyzeBlock()
    assert block.block_type == "structure_analyze"
    assert block.block_version == "1.27.0"
    assert block.category == "구조·보호"
    assert block.config_schema is sb.StructureAnalyzeConfig
    assert sb.StructureAnalyzeConfig().heading_max_level == 5


# ---- 쪽 정보가 없는 경로의 노드 쪽 번호(2026-11-16) ----
def test_legacy_nodes_get_page_numbers_from_page_map():
    text = "1. 서론\n첫 쪽 본문\n2. 본론\n둘째 쪽 본문"
    second_page_start = text.index("2. 본론")
    doc = _doc(page_map=[[second_page_start, 1], [len(text), 2]], parsed_text=text)

    _result, _db, nodes = _run(doc, text=text)

    pages = {n.text.split("\n")[0]: n.page_number for n in nodes if n.node_type != "DOCUMENT"}
    assert pages["1. 서론"] == 1
    assert pages["2. 본론"] == 2


def test_single_entry_page_map_leaves_page_unknown():
    text = "1. 서론\n본문"
    _result, _db, nodes = _run(_doc(page_map=[[len(text), 1]], parsed_text=text), text=text)
    assert all(n.page_number is None for n in nodes)


# ---- legacy 경로의 번호 제목 판정과 반복 줄(2026-11-16) ----
@pytest.mark.parametrize("line", [
    "5.07    5.08    5.86    5.11    4.93",          # 표의 숫자 행
    "005                                    000",
    "1805 월 B+ 시 BS 시스템",                         # 앞 번호가 너무 크다(연도·쪽·OCR 조각)
    "02 변기동ㆍ하미경. (2020). 지리적 특성을 고려한 범죄두려움 영향 요인 분석-범죄취약계층인 연구",  # 너무 길다
    "106          aoe              헤드리스브라우저를통한 렌더링",
    "29.94 | 26.59   37.21",
    "8 2022 MS 데이터 펠로우십 분석보고서",            # 쪽 번호 + 연도
    "3) 지역이 가진 지역 고유의 이미지가 지역의 GAIL 과잉 강조할 수 있다는 점(21610 et al,",
])
def test_ocr_and_table_lines_are_not_numbered_headings(line):
    assert sb._classify(line, None, None)[0] != "HEADING"


@pytest.mark.parametrize("line,level", [("1. 사업개요", 1), ("2.2.1. 디자인 검수 AI 서비스 개요", 3), ("3) 유저행동로그 DB 분석", 3)])
def test_real_numbered_headings_still_detected(line, level):
    assert sb._classify(line, None, None) == ("HEADING", level)


def _pages(*pages):
    text = "\n\n".join(pages)
    page_map, end = [], 0
    for i, page in enumerate(pages, start=1):
        end += len(page) + (2 if i < len(pages) else 0)
        page_map.append([end, i])
    return text, page_map


def test_lines_repeated_at_page_edges_become_headers():
    text, page_map = _pages(*(
        f"{n} 2022 서울 데이터 펠로우십 분석보고서\n1. 본문 제목 {n}\n내용 {n}\n내용 둘째 줄\n내용 셋째 줄" for n in (6, 8, 10)
    ))
    blocks = sb._build_blocks(text, page_map=page_map)
    headers = [b for b in blocks if b[0] == "HEADER"]
    assert len(headers) == 3
    assert all("펠로우십" in b[4] for b in headers)
    assert [b[4] for b in blocks if b[0] == "HEADING"] == ["1. 본문 제목 6", "1. 본문 제목 8", "1. 본문 제목 10"]


def test_footer_followed_by_a_table_block_is_still_a_page_edge_line():
    # 스캔 PDF 는 쪽의 표 글을 OCR 글 뒤에 붙인다. 표 줄 때문에 꼬리말이 쪽 끝 몇 줄에서 밀려나면 안 된다
    # (서울 데이터 펠로우십 보고서 12쪽·18쪽, 2026-11-20)
    table = "[표 4]\n| 변수 | 결과 |\n|---|---|\n| 가 | 1 |\n| 나 | 2 |"
    text, page_map = _pages(
        "본문 첫 줄\n내용\n6 2022 서울 데이터 펠로우십 분석보고서",
        f"본문 둘째 쪽\n내용\n8 2022 서울 데이터 펠로우십 분석보고서\n{table}",
        "본문 셋째 쪽\n내용\n10 2022 서울 데이터 펠로우십 분석보고서",
    )
    blocks = sb._build_blocks(text, page_map=page_map)
    assert len([b for b in blocks if b[0] == "HEADER" and "펠로우십" in b[4]]) == 3


def test_table_rows_at_page_edges_never_become_headers():
    # HWP 표 행은 맨 앞에 "|"가 없다("요구사항 고유번호 |  | MPR-002"). 쪽마다 반복돼도 표 내용이다(제안요청서)
    text, page_map = _pages(*(
        f"[표 {n}]\n요구사항 고유번호 |  | MPR-00{n}\n요구사항 명칭 |  | 항목 {n}\n본문 {n}\n본문 끝 {n}" for n in (1, 2, 3)
    ))
    blocks = sb._build_blocks(text, page_map=page_map)
    assert not [b for b in blocks if b[0] == "HEADER"]


def test_body_label_after_a_table_at_the_top_of_a_page_stays_in_body():
    # 쪽 머리의 표 다음에 오는 본문 소제목은 머리말이 아니다(조사료 지침 "《조사료 장거리 유통비 지원》")
    text, page_map = _pages(*(
        f"[표 {n}]\n농협경제지주(일선조합), 축산단체\n《조사료 장거리 유통비 지원》\n○ 본문 {n}\n○ 본문 끝 {n}"
        for n in (22, 25, 28)
    ))
    blocks = sb._build_blocks(text, page_map=page_map)
    assert not [b for b in blocks if b[0] == "HEADER"]


def test_table_title_line_after_a_table_marker_never_becomes_a_header():
    # 표 표시 바로 다음 줄은 표 제목이다(NS-AM 매뉴얼 "[칸 안의 표 1] [표 7]의 '설 명' 행의 칸에 든 표")
    text, page_map = _pages(*(
        f"[표 {n}]\n[칸 안의 표 1] [표 {n - 1}]의 '설 명' 행의 칸에 든 표\n| 가 | 나 |\n본문 {n}\n본문 끝 {n}"
        for n in (7, 9, 11)
    ))
    blocks = sb._build_blocks(text, page_map=page_map)
    assert not [b for b in blocks if b[0] == "HEADER"]


def test_repeated_body_lines_away_from_page_edges_stay_in_body():
    # 글머리표 줄이 쪽 끝(가장자리 후보)에 와도 머리말이 아니다
    body = "머리 첫 줄\n머리 둘째 줄\n가운데 본문 줄\n꼬리 첫 줄 내용\n• 위반 건수 : 2개 요소 확인"
    text, page_map = _pages(body, body.replace("첫", "1"), body.replace("첫", "2"))
    blocks = sb._build_blocks(text, page_map=page_map)
    assert not any("위반 건수" in b[4] for b in blocks if b[0] == "HEADER")


def test_without_page_map_nothing_is_marked_header():
    text = "\n\n".join(f"{n} 2022 서울 데이터 펠로우십 분석보고서\n본문" for n in (6, 8, 10))
    assert not [b for b in sb._build_blocks(text) if b[0] == "HEADER"]


def test_markup_numbered_list_lines_stay_list_items():
    # 마크다운 "1. 항목"은 제목이 아니라 목록 항목이다. 문단으로 합쳐지면 안 된다(리뷰 지적, 2026-11-19)
    entries = [{"text": t, "font_size": 11.0} for t in ["1. 첫째 항목", "2. 둘째 항목", "본문입니다.", "본문 둘", "본문 셋"]]
    text = "\n".join(e["text"] for e in entries)
    blocks = sb._build_blocks(text, entries, max_level=3, markup_headings=True)
    assert [(b[0], b[4]) for b in blocks[:2]] == [("LIST_ITEM", "1. 첫째 항목"), ("LIST_ITEM", "2. 둘째 항목")]


# ---- 문서 유형(2026-11-27) ----
REG_TEXT = "휴직규정\n제1장 총칙\n제1조(목적) 이 규정은 휴직을 정한다.\n제2조(정의) 정의는 다음과 같다.\n제2장 휴직\n제3조(종류) 종류는 다음과 같다."


def test_regulation_chosen_by_user_gets_article_headings_and_levels():
    doc = _doc(document_type="regulation", collection_id=None)

    _result, _db, nodes = _run(doc, text=REG_TEXT)

    headings = [(n.text, n.level) for n in nodes if n.node_type == "HEADING"]
    assert ("제1조(목적)", 2) in headings and ("제3조(종류)", 2) in headings
    assert ("제1장 총칙", 1) in headings and ("제2장 휴직", 1) in headings
    body = [n.text for n in nodes if n.node_type == "PARAGRAPH"]
    assert "이 규정은 휴직을 정한다." in body
    assert doc.detected_document_type == "general"  # 조가 셋뿐이라 자동 판별 기준(5)에는 못 미친다


def test_document_type_general_keeps_existing_structure():
    doc = _doc(document_type="general", collection_id=None)

    _result, _db, nodes = _run(doc, text=REG_TEXT)

    assert not any(n.text == "제1조(목적)" for n in nodes)


def test_regulation_is_detected_when_many_articles_follow():
    text = "\n".join(f"제{n}조(항목{n}) 본문 {n}입니다." for n in range(1, 7))
    doc = _doc(collection_id=None)

    _result, _db, nodes = _run(doc, text=text)

    assert doc.detected_document_type == "regulation"
    assert [n.text for n in nodes if n.node_type == "HEADING"][:2] == ["제1조(항목1)", "제2조(항목2)"]
