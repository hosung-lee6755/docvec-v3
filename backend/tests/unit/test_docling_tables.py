"""Docling 표를 행 목록으로 바꿀 때 번호 머리글(0, 1, 2…)을 쓰지 않는다.

Docling이 머리글 행을 알아보지 못하면 DataFrame 열 이름이 0, 1, 2가 된다. 예전에는 그것을 그대로
첫 행으로 써서 표 87개가 `| 0 | 1 | 2 |`로 시작하고 실제 머리글은 본문 첫 줄로 밀렸다(2026-11-13 검토).
"""
import pandas as pd

from app.pipeline.adapters.docling_adapter import _table_rows


class _Table:
    def __init__(self, df):
        self._df = df

    def export_to_dataframe(self):
        return self._df


def test_numbered_columns_use_the_first_row_as_header():
    df = pd.DataFrame([["구분", "지원한도", "기간"], ["고도화", "2억원", "6개월"]])

    rows = _table_rows(_Table(df))

    assert rows == [["구분", "지원한도", "기간"], ["고도화", "2억원", "6개월"]]


def test_named_columns_stay_as_header():
    df = pd.DataFrame([["고도화", "2억원"]], columns=["구분", "지원한도"])

    assert _table_rows(_Table(df)) == [["구분", "지원한도"], ["고도화", "2억원"]]


def test_numbered_columns_with_no_rows_give_no_table():
    assert _table_rows(_Table(pd.DataFrame())) == []


def test_string_digit_column_names_are_also_numbered():
    df = pd.DataFrame([["a", "b"], ["c", "d"]], columns=["0", "1"])

    assert _table_rows(_Table(df)) == [["a", "b"], ["c", "d"]]


# ---- 합친 칸(2026-11-17): export_to_dataframe()은 가로로 합친 칸의 글을 열마다 복사했다
class _Cell:
    def __init__(self, row, col, text, row_span=1, col_span=1):
        self.start_row_offset_idx, self.start_col_offset_idx = row, col
        self.row_span, self.col_span, self.text = row_span, col_span, text


class _GridTable:
    def __init__(self, cells):
        self.data = type("Data", (), {"table_cells": cells})()


def test_merged_cells_keep_their_text_once_across_columns_and_on_every_covered_row():
    from app.pipeline.adapters.docling_adapter import _table_grid

    table = _GridTable([
        _Cell(0, 0, "번호"), _Cell(0, 1, "판단기준", col_span=3), _Cell(0, 4, "필요서류"),
        _Cell(1, 0, "1"), _Cell(1, 1, "배관 보온", col_span=3), _Cell(1, 4, "시방서", row_span=2),
        _Cell(2, 0, "2"), _Cell(2, 1, "20"), _Cell(2, 2, "25"), _Cell(2, 3, "30"),
    ])

    rows, spans = _table_grid(table)

    assert rows == [
        ["번호", "판단기준", "", "", "필요서류"],
        ["1", "배관 보온", "", "", "시방서"],
        ["2", "20", "25", "30", "시방서"],
    ]
    assert {"row": 1, "col": 4, "row_span": 2, "col_span": 1} in spans


def test_tables_without_cell_data_fall_back_to_the_dataframe():
    from app.pipeline.adapters.docling_adapter import _table_grid

    rows, spans = _table_grid(_Table(pd.DataFrame([["a", "b"], ["c", "d"]])))

    assert rows == [["a", "b"], ["c", "d"]] and spans is None


def test_multi_row_headers_become_one_row_so_split_parts_keep_every_column_name():
    from app.pipeline.adapters.docling_adapter import _table_grid

    def head(row, col, text, **kw):
        cell = _Cell(row, col, text, **kw)
        cell.column_header = True
        return cell

    table = _GridTable([
        head(0, 0, "도시명", row_span=2), head(0, 1, "냉방", col_span=2), head(0, 3, "난방"),
        head(1, 1, "건구온도"), head(1, 2, "습구온도"), head(1, 3, "건구온도"),
        _Cell(2, 0, "서울"), _Cell(2, 1, "31.2"), _Cell(2, 2, "25.5"), _Cell(2, 3, "-11.3"),
    ])

    rows, _spans = _table_grid(table)

    assert rows == [["도시명", "냉방 건구온도", "냉방 습구온도", "난방 건구온도"], ["서울", "31.2", "25.5", "-11.3"]]


def test_a_table_without_caption_takes_the_title_line_right_above_it():
    # 기계설비 매뉴얼: 캡션 없는 표 바로 위 줄이 "[별표 1] 표 2 …" 같은 제목이다. 잘라 나눈 조각마다 제목을
    # 붙이려면 표 제목으로 받아야 한다(2026-11-19, 제목 없는 표 169개 중 50개가 이런 줄을 가짐)
    from app.pipeline.adapters.base import RawPage, RawTextBlock
    from app.pipeline.adapters.docling_adapter import _preceding_caption

    def page(*texts, last_type="paragraph"):
        blocks = [RawTextBlock(text=t, page_number=1) for t in texts]
        if blocks:
            blocks[-1].block_type = last_type
        return RawPage(page_number=1, width=1, height=1, text_blocks=blocks, table_candidates=[], image_regions=[])

    assert _preceding_caption(page("본문", "[별표 1] 표 2 냉·난방설비의 설계 외기온·습도 기준")) == (
        "[별표 1] 표 2 냉·난방설비의 설계 외기온·습도 기준"
    )
    assert _preceding_caption(page("<표 3-1> 실내 온도 기준")) == "<표 3-1> 실내 온도 기준"
    assert _preceding_caption(page("표 9 덕트 보온두께")) == "표 9 덕트 보온두께"
    assert _preceding_caption(page("설계 기준은 아래 표와 같다.")) is None
    assert _preceding_caption(page("[별표 1] 이전 표", last_type="table")) is None
    assert _preceding_caption(page("표 1 " + "가" * 120)) is None
    assert _preceding_caption(page()) is None
