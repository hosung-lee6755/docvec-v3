"""HTML 표의 rowspan/colspan을 HWPX와 같은 규칙(세로 병합은 글 되풀이, 가로 병합은 첫 칸만)으로 격자에 맞춘다."""
from app.pipeline.adapters.sheet_adapter import MAX_COLUMNS
from app.pipeline.adapters.simple_layout import BlockCollector
from app.pipeline.adapters.text_adapter import parse_html


def _table(inner: str):
    blocks, tables, _collector, _title = parse_html(f"<html><body><table>{inner}</table></body></html>")
    return blocks, tables


def test_rowspan_fills_following_rows_and_keeps_columns_aligned():
    _, tables = _table(
        "<tr><th>구분</th><th>항목</th><th>값</th></tr>"
        "<tr><td rowspan='2'>가</td><td>a</td><td>1</td></tr>"
        "<tr><td>b</td><td>2</td></tr>"
    )

    assert tables[0].rows == [["구분", "항목", "값"], ["가", "a", "1"], ["가", "b", "2"]]
    assert tables[0].spans == [{"row": 1, "col": 0, "row_span": 2, "col_span": 1}]


def test_colspan_writes_text_once_and_blanks_the_rest():
    _, tables = _table(
        "<tr><th colspan='2'>합계</th><th>비고</th></tr>"
        "<tr><td>a</td><td>b</td><td>c</td></tr>"
    )

    assert tables[0].rows == [["합계", "", "비고"], ["a", "b", "c"]]
    assert tables[0].spans == [{"row": 0, "col": 0, "row_span": 1, "col_span": 2}]


def test_rowspan_and_colspan_combined():
    _, tables = _table(
        "<tr><td rowspan='2' colspan='2'>큰칸</td><td>x</td></tr>"
        "<tr><td>y</td></tr>"
        "<tr><td>1</td><td>2</td><td>3</td></tr>"
    )

    assert tables[0].rows == [["큰칸", "", "x"], ["큰칸", "", "y"], ["1", "2", "3"]]
    assert tables[0].spans == [{"row": 0, "col": 0, "row_span": 2, "col_span": 2}]


def test_nested_table_is_text_of_outer_cell_and_not_spans():
    _, tables = _table(
        "<tr><td rowspan='2'>가</td><td><table><tr><td colspan='2'>안</td></tr></table>밖</td></tr>"
        "<tr><td>b</td></tr>"
    )

    assert len(tables) == 1
    assert tables[0].rows == [["가", "안 밖"], ["가", "b"]]
    assert tables[0].spans == [{"row": 0, "col": 0, "row_span": 2, "col_span": 1}]


def test_malformed_span_values_fall_back_to_one_or_are_clamped():
    _, tables = _table(
        "<tr><td rowspan='abc' colspan='x'>a</td><td rowspan='0' colspan='-3'>b</td>"
        f"<td colspan='99999'>c</td></tr>"
        "<tr><td>d</td><td>e</td></tr>"
    )

    rows = tables[0].rows
    assert rows[0][:3] == ["a", "b", "c"]
    assert len(rows[0]) <= MAX_COLUMNS and len(rows[1]) == len(rows[0])
    assert tables[0].spans == [{"row": 0, "col": 2, "row_span": 1, "col_span": MAX_COLUMNS - 2}]


def test_huge_rowspan_is_clamped_to_remaining_rows():
    _, tables = _table("<tr><td rowspan='99999'>a</td><td>1</td></tr><tr><td>2</td></tr>")

    assert tables[0].rows == [["a", "1"], ["a", "2"]]
    assert tables[0].spans == [{"row": 0, "col": 0, "row_span": 2, "col_span": 1}]


def test_plain_table_has_no_spans():
    _, tables = _table("<tr><td>a</td><td>b</td></tr>")

    assert tables[0].rows == [["a", "b"]] and not tables[0].spans


def test_markdown_block_uses_aligned_grid():
    blocks, _ = _table("<tr><th>구분</th><th>값</th></tr><tr><td rowspan='2'>가</td><td>1</td></tr><tr><td>2</td></tr>")

    table_text = next(b.text for b in blocks if b.block_type == "table")
    assert table_text.startswith("[표 1]")
    assert "| 가 | 1 |" in table_text and "| 가 | 2 |" in table_text


def test_empty_rows_are_dropped_and_spans_remapped():
    _, tables = _table(
        "<tr><td></td><td></td></tr>"
        "<tr><td rowspan='2'>가</td><td>1</td></tr>"
        "<tr><td>2</td></tr>"
    )

    assert tables[0].rows == [["가", "1"], ["가", "2"]]
    assert tables[0].spans == [{"row": 0, "col": 0, "row_span": 2, "col_span": 1}]


def test_collector_remaps_spans_when_dropping_empty_rows():
    collector = BlockCollector()
    blocks, tables = [], []

    collector.table(
        blocks, tables, [["", ""], ["가", "1"], ["가", "2"]], 1,
        spans=[{"row": 1, "col": 0, "row_span": 2, "col_span": 1}],
    )

    assert tables[0].rows == [["가", "1"], ["가", "2"]]
    assert tables[0].spans == [{"row": 0, "col": 0, "row_span": 2, "col_span": 1}]
