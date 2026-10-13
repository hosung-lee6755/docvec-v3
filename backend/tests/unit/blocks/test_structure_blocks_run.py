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
    assert block.block_version == "1.9.0"
    assert block.category == "구조·보호"
    assert block.config_schema is sb.StructureAnalyzeConfig
    assert sb.StructureAnalyzeConfig().heading_max_level == 3
