"""chunk_strategies: 문장 분할/표 행 분할/트리 분할 분기 보강 테스트."""
from types import SimpleNamespace

from app.pipeline.blocks import chunk_strategies as cs


def _node(nid, ntype, start, end, text=None, level=None, **kw):
    return SimpleNamespace(
        id=nid, node_type=ntype, span_start=start, span_end=end, text=text, level=level,
        source_table_id=kw.get("source_table_id"),
    )


def _tree(nodes, text, **kw):
    params = dict(
        max_chars=100, min_chars=0, respect_headings=False, include_previous_heading=False,
        preserve_table=True, split_long_paragraph=True,
    )
    params.update(kw)
    return cs._tree_based_chunks(nodes, text, **params)


# ---- 문장 기반 ----
def test_sentence_chunks_empty_text():
    assert cs._sentence_based_chunks("", 100, 10) == []


def test_sentence_chunks_split_at_max_chars_on_sentence_boundary():
    text = "첫 번째 문장입니다. 두 번째 문장입니다. 세 번째 문장입니다."
    chunks = cs._sentence_based_chunks(text, max_chars=25, min_chars=0)
    assert len(chunks) >= 2
    assert all(text[c.start:c.end] == c.text for c in chunks)
    assert chunks[0].text.endswith("다.")


def test_sentence_chunks_merge_short_tail_into_previous():
    text = "첫 번째 문장입니다. 두 번째 문장입니다. 끝."
    unmerged = cs._sentence_based_chunks(text, max_chars=22, min_chars=0)
    merged = cs._sentence_based_chunks(text, max_chars=22, min_chars=50)
    assert len(merged) == len(unmerged) - 1
    assert merged[-1].end == len(text)


# ---- 표 행 ----
ROWS = [["항목", "값"], ["a", "1"], ["b", "2"], ["c", "3"], ["d", "4"]]


def test_table_rows_and_ordinal_lookup():
    tables = [{"id": "t1", "rows": ROWS}, {"id": "t2", "rows": [["x"]]}]
    assert cs._table_rows_and_ordinal("t2", tables) == ([["x"]], 2)
    assert cs._table_rows_and_ordinal("none", tables) == (None, None)
    assert cs._table_rows_and_ordinal(None, tables) == (None, None)
    assert cs._table_rows_and_ordinal("t1", None) == (None, None)


def test_split_table_rows_empty_and_header_only():
    assert cs._split_table_rows([], 1, 100, None) == []
    only_header = cs._split_table_rows([["h1", "h2"]], 1, 100, None)
    assert len(only_header) == 1 and "(부분" not in only_header[0]


def test_split_table_rows_by_max_rows_repeats_header():
    parts = cs._split_table_rows(ROWS, 3, 1000, max_rows=2)
    assert len(parts) == 2
    assert parts[0].startswith("[표 3] (부분 1/2)")
    assert all("항목" in p for p in parts)


def test_split_table_rows_by_chars_and_missing_ordinal_label():
    parts = cs._split_table_rows(ROWS, None, max_chars=1, max_rows=None)
    assert len(parts) == 4
    assert parts[0].startswith("(부분 1/4)")


def test_split_table_rows_by_chars_single_group_when_small():
    parts = cs._split_table_rows(ROWS, 1, max_chars=10_000, max_rows=None)
    assert len(parts) == 1 and parts[0].startswith("[표 1] (부분 1/1)")


# ---- 트리 기반 ----
def test_tree_skips_document_root_and_nodes_without_span():
    text = "본문입니다"
    nodes = [
        _node("r", "DOCUMENT", 0, len(text)),
        _node("n1", "PARAGRAPH", None, None),
        _node("n2", "PARAGRAPH", 0, len(text)),
    ]
    chunks = _tree(nodes, text)
    assert [c.source_node_ids for c in chunks] == [["n2"]]


def test_tree_tables_only_skips_other_nodes_but_tracks_headings():
    text = "제목\n\n본문\n\n[표 1]"
    nodes = [
        _node("h", "HEADING", 0, 2, "제목", level=1),
        _node("p", "PARAGRAPH", 4, 6),
        _node("t", "TABLE", 8, len(text)),
    ]
    chunks = _tree(nodes, text, tables_only=True)
    assert len(chunks) == 1
    assert chunks[0].section_path == ["제목"] and chunks[0].source_node_ids == ["t"]


def test_tree_include_previous_heading_prefixes_chunk():
    text = "1장\n\n내용 문단"
    nodes = [_node("h", "HEADING", 0, 2, "1장", level=1), _node("p", "PARAGRAPH", 4, len(text))]
    chunks = _tree(nodes, text, include_previous_heading=True)
    assert chunks[0].text == "[1장]\n내용 문단"
    assert chunks[0].section_path == ["1장"]


def test_tree_respect_headings_closes_chunk_at_each_heading():
    text = "A절\n\n가나다\n\nB절\n\n라마바"
    nodes = [
        _node("h1", "HEADING", 0, 2, "A절", level=1), _node("p1", "PARAGRAPH", 4, 7),
        _node("h2", "HEADING", 9, 11, "B절", level=1), _node("p2", "PARAGRAPH", 13, 16),
    ]
    chunks = _tree(nodes, text, respect_headings=True)
    assert [c.section_path for c in chunks] == [["A절"], ["B절"]]


def test_tree_heading_stack_pops_to_same_or_higher_level():
    text = "x" * 40
    nodes = [
        _node("h1", "HEADING", 0, 1, "상위", level=1),
        _node("h2", "HEADING", 1, 2, "하위", level=2),
        _node("h3", "HEADING", 2, 3, "새 상위", level=1),
        _node("p", "PARAGRAPH", 5, 10),
        _node("hn", "HEADING", 10, 11, "레벨없음", level=None),
        _node("p2", "PARAGRAPH", 12, 20),
    ]
    chunks = _tree(nodes, text, respect_headings=True)
    assert chunks[0].section_path == ["새 상위"]
    assert chunks[1].section_path == ["레벨없음"]


def test_tree_overflow_flushes_buffer_before_adding():
    text = "a" * 60 + "\n\n" + "b" * 60
    nodes = [_node("p1", "PARAGRAPH", 0, 60), _node("p2", "PARAGRAPH", 62, 122)]
    chunks = _tree(nodes, text, max_chars=100)
    assert [c.source_node_ids for c in chunks] == [["p1"], ["p2"]]


def test_tree_small_nodes_merge_into_one_chunk():
    text = "aaa\n\nbbb"
    nodes = [_node("p1", "PARAGRAPH", 0, 3), _node("p2", "PARAGRAPH", 5, 8)]
    chunks = _tree(nodes, text)
    assert len(chunks) == 1 and chunks[0].source_node_ids == ["p1", "p2"]


def test_tree_long_paragraph_split_or_kept_whole():
    text = "가나다라 " * 60
    nodes = [_node("p", "PARAGRAPH", 0, len(text))]
    split = _tree(nodes, text, max_chars=50)
    whole = _tree(nodes, text, max_chars=50, split_long_paragraph=False)
    assert len(split) > 1 and all(c.source_node_ids == ["p"] for c in split)
    assert len(whole) == 1 and (whole[0].start, whole[0].end) == (0, len(text))


def test_tree_oversized_table_uses_row_groups_with_source_span():
    text = "[표 1]" + "x" * 200
    rows = [["h", "v"]] + [[f"r{i}", str(i)] for i in range(6)]
    nodes = [_node("t", "TABLE", 0, len(text), source_table_id="tid")]
    chunks = _tree(nodes, text, max_chars=50, tables=[{"id": "tid", "rows": rows}], table_chunk_max_rows=3,
                   include_previous_heading=True)
    assert len(chunks) == 2
    assert all((c.start, c.end) == (0, len(text)) for c in chunks)
    assert chunks[0].text.startswith("[표 1] (부분 1/2)")


def test_tree_oversized_table_without_rows_falls_back_to_char_split():
    text = "[표 1]\n" + "셀 | 값\n" * 40
    nodes = [_node("t", "TABLE", 0, len(text), source_table_id="missing")]
    chunks = _tree(nodes, text, max_chars=60, tables=[{"id": "other", "rows": [["a"]]}])
    assert len(chunks) > 1
    assert all(c.source_node_ids == ["t"] for c in chunks)


def test_tree_table_not_preserved_merges_like_paragraph():
    text = "본문\n\n[표 1] a | b"
    nodes = [_node("p", "PARAGRAPH", 0, 2), _node("t", "TABLE", 4, len(text))]
    chunks = _tree(nodes, text, preserve_table=False)
    assert len(chunks) == 1


def test_tree_tail_merge_same_section_not_for_tables():
    text = "가" * 50 + "\n\n" + "나" * 50 + "\n\n끝"
    nodes = [
        _node("p1", "PARAGRAPH", 0, 50), _node("p2", "PARAGRAPH", 52, 112), _node("p3", "PARAGRAPH", 114, 115),
    ]
    merged = _tree(nodes, text, max_chars=60, min_chars=10, include_previous_heading=True)
    assert merged[-1].source_node_ids == ["p2", "p3"]
    assert merged[-1].end == 115

    t_nodes = [_node("p1", "PARAGRAPH", 0, 50), _node("t", "TABLE", 114, 115)]
    kept = _tree(t_nodes, text, max_chars=60, min_chars=10)
    assert len(kept) == 2


def test_tree_tail_merge_skipped_across_sections():
    text = "A\n\n" + "가" * 50 + "\n\nB\n\n끝"
    nodes = [
        _node("h1", "HEADING", 0, 1, "A", level=1), _node("p1", "PARAGRAPH", 3, 53),
        _node("h2", "HEADING", 55, 56, "B", level=1), _node("p2", "PARAGRAPH", 58, 59),
    ]
    chunks = _tree(nodes, text, respect_headings=True, min_chars=10)
    assert len(chunks) == 2


# ---- 부모 그룹 ----
def _span(start, end, path=None):
    return ("c", "r", start, end, path or [], [])


def test_group_children_flat_groups_of_five():
    spans = [_span(i * 10, i * 10 + 5) for i in range(7)]
    assert cs.group_children_into_parents(spans, max_chars=1000) == [[0, 1, 2, 3, 4], [5, 6]]


def test_group_children_split_on_section_change_and_size():
    spans = [_span(0, 5, ["A"]), _span(6, 11, ["A"]), _span(12, 17, ["B"]), _span(1000, 1005, ["B"])]
    assert cs.group_children_into_parents(spans, max_chars=10) == [[0, 1], [2], [3]]
    assert cs.group_children_into_parents([], 10) == []


def test_estimate_token_count_mixes_hangul_and_other():
    assert cs._estimate_token_count("") == 0
    assert cs._estimate_token_count("가나다") == 3
    assert cs._estimate_token_count("abcdefgh") == 2
    assert cs._estimate_token_count("a") == 1



# ---- 짧은 구획 합치기(자동 구조 기준, 2026-11-13) ----
# 소제목이 촘촘한 슬라이드형 PDF에서 제목마다 청크를 닫으면 6~50자짜리 조각이 쏟아졌다.


def _slides():
    parts = [("H", "개요", 1), ("P", "요구사항 정의", None), ("H", "세부", 1),
             ("P", "사전분석을 통한 제안사 의견 도출 및 제시입니다.", None),
             ("H", "결과", 1), ("T", "| 항목 | 값 | 비고 | 가 | 1 | 없음 |", None), ("H", "끝", 1), ("P", "짧음", None)]
    text, nodes = "", []
    for i, (kind, body, level) in enumerate(parts):
        if text:
            text += "\n\n"
        start = len(text)
        text += body
        node_type = {"H": "HEADING", "P": "PARAGRAPH", "T": "TABLE"}[kind]
        nodes.append(_node(f"n{i}", node_type, start, len(text), text=body, level=level))
    return text, nodes


def test_short_sections_are_merged_with_a_neighbour_when_asked():
    text, nodes = _slides()

    chunks = _tree(nodes, text, max_chars=200, min_chars=20, respect_headings=True, merge_small_sections=True)

    bodies = [c.text for c in chunks]
    assert bodies[0] == "요구사항 정의\n\n세부\n\n사전분석을 통한 제안사 의견 도출 및 제시입니다."
    assert chunks[0].section_path == ["세부"]  # 더 긴 쪽의 구획 경로를 따른다
    assert "| 항목 | 값 | 비고 | 가 | 1 | 없음 |" in bodies  # 표는 다른 내용과 섞지 않는다


def test_short_sections_stay_apart_by_default():
    text, nodes = _slides()

    chunks = _tree(nodes, text, max_chars=200, min_chars=20, respect_headings=True)

    assert chunks[0].text == "요구사항 정의"


def test_merging_never_exceeds_max_chars():
    text, nodes = _slides()

    chunks = _tree(nodes, text, max_chars=30, min_chars=20, respect_headings=True, merge_small_sections=True)

    assert chunks[0].text == "요구사항 정의"



def test_a_tiny_title_table_is_merged_like_a_heading():
    # HWP 공고문은 칸 하나짜리 표를 장 제목으로 쓴다
    title = "[표 1] 1. 사업개요 |"
    body = "중소기업의 공장 자동화를 지원하는 사업입니다."
    text = title + "XX" + body
    nodes = [_node("t", "TABLE", 0, len(title)), _node("p", "PARAGRAPH", len(title) + 2, len(text))]

    chunks = _tree(nodes, text, max_chars=200, min_chars=30, respect_headings=True, merge_small_sections=True)

    assert len(chunks) == 1 and chunks[0].text.startswith(title)



def test_a_short_line_right_before_a_table_becomes_its_title():
    # 표 사이에 낀 "※ ... 비교표" 한 줄은 바로 뒤 표의 제목이다. 앞 표에는 붙이지 않는다
    first = "| 구분 | 내용 | 비고 | 가 | 나 | 다 | 라 |"
    caption = "※ 대안 프레임워크 비교표"
    second = "| 이름 | 장점 | 단점 | 리액트 | 생태계 | 무거움 |"
    text = first + "XX" + caption + "XX" + second
    a, b = len(first) + 2, len(first) + 2 + len(caption)
    nodes = [_node("t1", "TABLE", 0, len(first)), _node("p", "PARAGRAPH", a, b),
             _node("t2", "TABLE", b + 2, len(text))]

    chunks = _tree(nodes, text, max_chars=200, min_chars=30, respect_headings=True, merge_small_sections=True)

    assert [c.text for c in chunks] == [first, caption + "XX" + second]
