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
