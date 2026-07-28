from types import SimpleNamespace

from app.pipeline.blocks.chunk_strategies import _tree_based_chunks


def _node(node_type, text, span_start, span_end, level=None, id="x"):
    return SimpleNamespace(
        node_type=node_type, text=text, span_start=span_start, span_end=span_end, level=level, id=id
    )


def test_tail_merge_does_not_absorb_a_table_chunk():
    # preserve_table guarantees a TABLE node is always its own chunk. The
    # tail-merge step (last chunk under min_chars gets folded into the
    # previous one) used to only check section_path equality, so a short
    # table immediately followed by a short trailing paragraph in the same
    # section got silently merged into one mixed chunk — breaking that
    # guarantee (문서 파싱 고도화 회고, 2026-07-23).
    para = "PARA_LONG_TEXT_HERE_FILLER_TO_PASS_MIN_CHARS_1234567890"
    table_text = "|TABLE_ROW_A|TABLE_ROW_B"
    tail_text = "|TAIL"
    full_text = para + table_text + tail_text

    nodes = [
        _node("PARAGRAPH", "para", 0, len(para), id="p1"),
        _node("TABLE", "table", len(para), len(para) + len(table_text), id="t1"),
        _node(
            "PARAGRAPH", "tail",
            len(para) + len(table_text), len(full_text), id="p2",
        ),
    ]

    chunks = _tree_based_chunks(
        nodes, full_text,
        max_chars=1000, min_chars=1000,
        respect_headings=False, include_previous_heading=False,
        preserve_table=True, split_long_paragraph=False,
    )

    table_chunks = [c for c in chunks if c.source_node_ids == ["t1"]]
    assert len(table_chunks) == 1
    assert "TAIL" not in table_chunks[0].text
    assert all("p2" not in c.source_node_ids for c in chunks if "t1" in c.source_node_ids)


def test_tail_merge_still_combines_two_short_non_table_chunks_in_same_section():
    # Regression guard: the new table check must not disable the existing
    # tail-merge behavior for ordinary short paragraphs.
    first = "FIRST_SHORT"
    second = "SECOND_SHORT"
    full_text = first + second

    nodes = [
        _node("PARAGRAPH", "first", 0, len(first), id="p1"),
        _node("PARAGRAPH", "second", len(first), len(full_text), id="p2"),
    ]

    chunks = _tree_based_chunks(
        nodes, full_text,
        max_chars=1000, min_chars=1000,
        respect_headings=False, include_previous_heading=False,
        preserve_table=True, split_long_paragraph=False,
    )

    assert len(chunks) == 1
    assert chunks[0].source_node_ids == ["p1", "p2"]
