from app.pipeline.blocks.structure_blocks import (
    _build_blocks_from_elements,
    _node_type_for_element,
)


def _el(el_type, text="본문", el_id="el-1", page=1, span=(0, 4), metadata=None):
    return {
        "id": el_id, "page": page, "type": el_type, "bbox": None,
        "content": {"text": text, "markdown": text},
        "metadata": metadata or {},
        "span_start": span[0] if span else None,
        "span_end": span[1] if span else None,
    }


def test_docling_type_mapping_covers_every_known_label():
    cases = {
        "title": "HEADING",
        "section_header": "HEADING",
        "table": "TABLE",
        "list_item": "LIST_ITEM",
        "picture": "IMAGE",
        "figure": "IMAGE",
        "caption": "CAPTION",
        "footnote": "FOOTNOTE",
        "page_header": "HEADER",
        "page_footer": "FOOTER",
        "document_index": "TOC",
        "text": "PARAGRAPH",
    }
    for docling_type, expected_node_type in cases.items():
        assert _node_type_for_element(docling_type) == expected_node_type


def test_toc_element_survives_even_with_empty_content():
    # Phase 1에서 발견한 실제 갭: document_index 요소의 content가 비어 있을 수
    # 있다 — 그래도 TOC 노드 자체는 만들어져야 "목차가 제목/문단으로 오분류"
    # 되던 문제가 해결된 채로 유지된다.
    elements = [_el("document_index", text="")]

    blocks = _build_blocks_from_elements(elements)

    assert len(blocks) == 1
    assert blocks[0][0] == "TOC"


def test_empty_paragraph_element_is_skipped():
    elements = [_el("text", text=""), _el("text", text="실제 문단", el_id="el-2")]

    blocks = _build_blocks_from_elements(elements)

    assert len(blocks) == 1
    assert blocks[0][4] == "실제 문단"


def test_heading_level_comes_from_metadata_with_fallback_to_one():
    elements = [
        _el("section_header", text="제목 A", metadata={"level": 2}),
        _el("title", text="문서 제목", el_id="el-2"),
    ]

    blocks = _build_blocks_from_elements(elements)

    levels = {b[4]: b[1] for b in blocks}
    assert levels["제목 A"] == 2
    assert levels["문서 제목"] == 1


def test_table_element_carries_span_and_element_id_for_source_table_id_lookup():
    elements = [_el("table", text="| a | b |", el_id="table-uuid", span=(10, 20))]

    blocks = _build_blocks_from_elements(elements)

    node_type, level, span_start, span_end, block_text, layout = blocks[0]
    assert node_type == "TABLE"
    assert (span_start, span_end) == (10, 20)
    assert block_text == "| a | b |"
    assert layout["element_id"] == "table-uuid"
    assert layout["page_number"] == 1


def test_picture_element_kept_without_text_and_without_span():
    elements = [_el("picture", text="", span=None)]

    blocks = _build_blocks_from_elements(elements)

    assert len(blocks) == 1
    node_type, level, span_start, span_end, block_text, layout = blocks[0]
    assert node_type == "IMAGE"
    assert (span_start, span_end) == (None, None)


def test_reading_order_preserved_from_input_list():
    elements = [
        _el("title", text="제목", el_id="e1"),
        _el("text", text="문단1", el_id="e2"),
        _el("table", text="표", el_id="e3"),
        _el("text", text="문단2", el_id="e4"),
    ]

    blocks = _build_blocks_from_elements(elements)

    assert [b[4] for b in blocks] == ["제목", "문단1", "표", "문단2"]
