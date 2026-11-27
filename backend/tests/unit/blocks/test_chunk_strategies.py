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


def test_a_chapter_heading_followed_by_an_article_is_not_a_chunk_of_its_own():
    # 규정의 "제2장 복무" 한 줄 청크가 검색 후보를 차지해 정답 조문을 밀어냈다(청원경찰복무규정, 2026-11-27).
    # 장 제목은 뒤 조 청크의 구획 경로에 남는다
    chapter, article, body = "제2장 복무\n", "제3조(근무제)\n", "① 근무는 격일제로 한다."
    text = chapter + article + body
    a, b = len(chapter), len(chapter) + len(article)
    nodes = [
        _node("HEADING", "제2장 복무", 0, a - 1, level=1, id="h1"),
        _node("HEADING", "제3조(근무제)", a, b - 1, level=2, id="h2"),
        _node("PARAGRAPH", body, b, len(text), id="p1"),
    ]

    chunks = _tree_based_chunks(
        nodes, text, max_chars=500, min_chars=1,
        respect_headings=True, include_previous_heading=False,
        preserve_table=True, split_long_paragraph=True,
    )

    assert len(chunks) == 1
    assert chunks[0].section_path == ["제2장 복무", "제3조(근무제)"]
    assert chunks[0].text.startswith("제3조(근무제)")


def test_a_heading_without_body_is_still_kept_as_text():
    # 본문 없는 제목은 어느 구획 경로에도 남지 않으므로 예전처럼 글로 담는다
    first, second = "제4조(효력기간) 본 협정서는 1년간 유효하다.\n", "제5조(해석)\n"
    text = first + second + "해석은 협의한다."
    nodes = [
        _node("HEADING", first.strip(), 0, len(first) - 1, level=1, id="h1"),
        _node("HEADING", "제5조(해석)", len(first), len(first + second) - 1, level=1, id="h2"),
        _node("PARAGRAPH", "해석은 협의한다.", len(first + second), len(text), id="p1"),
    ]

    chunks = _tree_based_chunks(
        nodes, text, max_chars=500, min_chars=1,
        respect_headings=True, include_previous_heading=False,
        preserve_table=True, split_long_paragraph=True,
    )

    assert any("효력기간" in c.text for c in chunks)
