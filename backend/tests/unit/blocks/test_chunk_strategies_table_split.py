from types import SimpleNamespace

from app.pipeline.blocks.chunk_strategies import (
    _split_table_rows,
    _table_rows_and_ordinal,
    _tree_based_chunks,
)


def _node(node_type, text, span_start, span_end, level=None, id="x", source_table_id=None):
    return SimpleNamespace(
        node_type=node_type, text=text, span_start=span_start, span_end=span_end,
        level=level, id=id, source_table_id=source_table_id,
    )


def _big_table(num_rows):
    header = ["Name", "Age"]
    rows = [header] + [[f"Person{i}", str(20 + i)] for i in range(num_rows)]
    return rows


def test_table_rows_and_ordinal_finds_match_by_id():
    tables = [{"id": "t-a", "rows": [["h"]]}, {"id": "t-b", "rows": [["h2"]]}]

    rows, ordinal = _table_rows_and_ordinal("t-b", tables)

    assert rows == [["h2"]]
    assert ordinal == 2


def test_table_rows_and_ordinal_returns_none_when_not_found():
    assert _table_rows_and_ordinal("missing", [{"id": "t-a", "rows": [["h"]]}]) == (None, None)
    assert _table_rows_and_ordinal(None, [{"id": "t-a", "rows": [["h"]]}]) == (None, None)
    assert _table_rows_and_ordinal("t-a", None) == (None, None)


def test_split_table_rows_repeats_header_in_every_group_by_row_count():
    rows = _big_table(5)

    parts = _split_table_rows(rows, ordinal=1, max_chars=10_000, max_rows=2)

    assert len(parts) == 3  # 5 body rows / 2 per group -> 3, 2, 1
    for i, part in enumerate(parts, start=1):
        assert "| Name | Age |" in part
        assert f"(부분 {i}/3)" in part
    # no row lost or duplicated across groups
    all_names = "".join(parts)
    for i in range(5):
        assert all_names.count(f"Person{i} ") == 1


def test_split_table_rows_greedy_by_char_budget_when_no_max_rows():
    rows = _big_table(20)

    parts = _split_table_rows(rows, ordinal=None, max_chars=120, max_rows=None)

    assert len(parts) > 1
    for part in parts:
        assert "| Name | Age |" in part
    all_text = "".join(parts)
    for i in range(20):
        assert all_text.count(f"Person{i} ") == 1


def test_split_table_rows_single_group_when_it_fits():
    rows = _big_table(2)

    parts = _split_table_rows(rows, ordinal=3, max_chars=10_000, max_rows=None)

    assert len(parts) == 1
    assert "(부분 1/1)" in parts[0]


def test_oversized_table_node_splits_into_row_groups_via_tree_based_chunks():
    table_text = "| Name | Age |\n|---|---|\n" + "\n".join(f"| Person{i} | {20+i} |" for i in range(30))
    full_text = table_text
    tables = [{"id": "table-uuid", "rows": _big_table(30)}]

    nodes = [_node("TABLE", table_text, 0, len(full_text), id="t1", source_table_id="table-uuid")]

    chunks = _tree_based_chunks(
        nodes, full_text,
        max_chars=200, min_chars=0,
        respect_headings=False, include_previous_heading=False,
        preserve_table=True, split_long_paragraph=True,
        tables=tables, table_chunk_max_rows=None,
    )

    assert len(chunks) > 1
    assert all(c.source_node_ids == ["t1"] for c in chunks)
    for chunk in chunks:
        assert "| Name | Age |" in chunk.text
    combined = "".join(c.text for c in chunks)
    for i in range(30):
        assert combined.count(f"Person{i} ") == 1


def test_oversized_table_without_matching_rows_falls_back_to_character_cut():
    # No `tables` provided (e.g. legacy 문서 재처리 이전 데이터) — must behave
    # exactly like before this phase: plain character-cut, not row grouping.
    table_text = "X" * 500
    nodes = [_node("TABLE", table_text, 0, len(table_text), id="t1", source_table_id="table-uuid")]

    chunks = _tree_based_chunks(
        nodes, table_text,
        max_chars=200, min_chars=0,
        respect_headings=False, include_previous_heading=False,
        preserve_table=True, split_long_paragraph=True,
        tables=None, table_chunk_max_rows=None,
    )

    assert len(chunks) > 1
    assert all("Name" not in c.text for c in chunks)
    assert "".join(c.text for c in chunks) == table_text


def test_non_table_oversized_paragraph_is_unaffected_by_table_split_logic():
    para_text = "P" * 500
    nodes = [_node("PARAGRAPH", para_text, 0, len(para_text), id="p1")]
    tables = [{"id": "unrelated", "rows": [["h"]]}]

    chunks = _tree_based_chunks(
        nodes, para_text,
        max_chars=200, min_chars=0,
        respect_headings=False, include_previous_heading=False,
        preserve_table=True, split_long_paragraph=True,
        tables=tables, table_chunk_max_rows=None,
    )

    assert len(chunks) > 1
    assert "".join(c.text for c in chunks) == para_text


# ---- 행 하나가 max_chars보다 긴 표(2026-11-17: 표 조각만 2000자를 넘던 문제)
def _long_row_table():
    long_cell = " ".join(f"{i}번째 문장은 판단 근거를 설명합니다." for i in range(60))
    return [["구분", "판단기준", "필요서류"], ["보온", long_cell, "시험성적서"], ["배관", "짧은 기준", "도면"]]


def test_a_row_longer_than_the_budget_is_split_at_sentence_boundaries():
    rows = _long_row_table()

    parts = _split_table_rows(rows, ordinal=22, max_chars=500, max_rows=None)

    assert len(parts) > 2
    for part in parts:
        body = part.split("\n", 1)[1]
        assert len(body) <= 500
        assert "| 구분 | 판단기준 | 필요서류 |" in part
    long_parts = [p for p in parts if "번째 문장" in p]
    # 나뉜 조각마다 첫 열(행 이름)이 남아 어떤 행의 이어지는 글인지 알 수 있다
    assert all("| 보온 |" in p for p in long_parts)
    joined = "".join(parts)
    for i in range(60):
        assert f"{i}번째 문장은" in joined
    assert joined.count("시험성적서") == 1 and "| 배관 | 짧은 기준 | 도면 |" in joined


def test_a_single_sentence_longer_than_the_budget_is_cut_by_characters():
    rows = [["구분", "내용"], ["가", "나" * 1500]]

    parts = _split_table_rows(rows, ordinal=None, max_chars=400, max_rows=None)

    assert len(parts) >= 4
    assert all(len(p.split("\n", 1)[1]) <= 400 for p in parts)
    assert "".join(parts).count("나") == 1500


def test_every_part_of_a_titled_table_carries_the_title():
    parts = _split_table_rows(_big_table(20), ordinal=7, max_chars=120, max_rows=None, title="직원 명부")

    assert len(parts) > 1
    assert all(part.startswith("[표 7] 직원 명부 (부분 ") for part in parts)
