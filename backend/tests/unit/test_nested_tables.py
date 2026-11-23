"""칸 안의 표(안쪽 표)를 바깥 표와 잇는 표시와 제목(2026-11-20, NS-AM 검사매뉴얼 검토)."""
from app.pipeline.adapters.nested_tables import (
    InnerTables,
    host_cell,
    is_frame_only,
    is_separable_table,
    nested_marker,
    nested_table_title,
    strip_nested_markers,
)


def test_marker_numbers_the_inner_tables_of_one_outer_table():
    assert nested_marker(1) == "[칸 안의 표 1]"
    assert nested_marker(2) == "[칸 안의 표 2]"


def test_title_names_the_row_and_column_of_the_host_cell():
    outer = [
        ["No", "Criteria", "Basis"],
        ["1", "General", "2.3.1"],
        ["2", f"Meter box rule {nested_marker(1)}", "2.3.5"],
    ]

    assert nested_table_title(outer, 1) == "[칸 안의 표 1] '2' 행 'Criteria' 열 칸에 든 표"


def test_title_uses_only_the_row_label_when_the_header_cell_is_empty():
    outer = [
        ["NS-AM형 선로전환기 검사 메뉴얼", "", "", "Rev. A"],
        ["설    명", "", f"부품 재료 / {nested_marker(1)}", ""],
    ]

    assert nested_table_title(outer, 1) == "[칸 안의 표 1] '설 명' 행의 칸에 든 표"


def test_title_keeps_the_outer_title_and_the_inner_caption():
    outer = [["구분", "내용"], ["재료", nested_marker(1)]]

    title = nested_table_title(outer, 1, outer_title="검사 항목", name="[표 2] 재질 규격")

    assert title == "[칸 안의 표 1] [표 2] 재질 규격 (검사 항목의 '재료' 행 '내용' 열 칸에 든 표)"


def test_title_without_a_marker_in_the_outer_table_points_to_the_table_above():
    assert nested_table_title([["a", "b"], ["c", "d"]], 1) == "[칸 안의 표 1] 바로 위 표 안에 든 표"


def test_long_labels_are_shortened():
    outer = [["가" * 40, "열"], ["행", nested_marker(1)]]

    assert nested_table_title(outer, 1) == "[칸 안의 표 1] '행' 행 '열' 열 칸에 든 표"
    outer = [["머리", "열"], ["나" * 40, nested_marker(1)]]
    assert "'" + "나" * 20 + "…'" in nested_table_title(outer, 1)


def test_markers_are_removed_for_text_matching():
    assert strip_nested_markers(f"설명 / {nested_marker(1)} / 끝{nested_marker(12)}") == "설명 /  / 끝"


def test_only_tables_with_two_rows_and_two_columns_are_separated():
    assert is_separable_table([["a", "b"], ["c", "d"]])
    assert not is_separable_table([["a", "b"]])  # 한 줄짜리 상자는 칸 글로 둔다
    assert not is_separable_table([["a"], ["b"]])
    assert not is_separable_table([])


def test_a_single_cell_frame_holding_only_inner_tables_is_not_a_table():
    # R&D 스마트공장 공고의 추진체계도, 2021 조사료 지침의 시료 채취량 표는 칸 하나짜리 틀 안에 표만 들어 있다
    assert is_frame_only([[nested_marker(1)]])
    assert is_frame_only([[f"{nested_marker(1)} / {nested_marker(2)}"]])
    assert not is_frame_only([[f"※ 참고 {nested_marker(1)}"]])  # 틀에 다른 글이 있으면 그대로 둔다
    assert not is_frame_only([[nested_marker(1), "b"]])


def test_title_of_a_table_in_a_full_width_row_names_the_row_above():
    # 고도화보고서(HTML): 항목 줄 아래에 표 폭 전체를 차지하는 설명 줄이 있고, 그 안에 표가 있다
    outer = [
        ["항목", "이전", "고도화"],
        ["운전자 하루 거리", "누적 차이", "자정에서 나눔"],
        [f"왜 바꿨나 {nested_marker(1)}", "", ""],
    ]

    assert nested_table_title(outer, 1) == "[칸 안의 표 1] '운전자 하루 거리' 행 아래 칸에 든 표"


def test_inner_table_titles_are_recognized():
    from app.pipeline.adapters.nested_tables import is_inner_table_title

    assert is_inner_table_title("[칸 안의 표 1] '설 명' 행의 칸에 든 표")
    assert not is_inner_table_title("표 2 선로전환기의 특징 비교")
    assert not is_inner_table_title(None)


# ---- 표 B 가 표 A 의 어느 칸에 있었는지 JSON 으로 남긴다(2026-11-20, parent_table_id·parent_cell)

def test_host_cell_is_the_zero_based_cell_holding_the_marker():
    outer = [["구분", "내용"], ["설명", "주요 부품 / [칸 안의 표 1]"], ["비고", "[칸 안의 표 2]"]]
    assert host_cell(outer, 1) == {"row": 1, "col": 1}
    assert host_cell(outer, 2) == {"row": 2, "col": 1}
    assert host_cell(outer, 3) is None


def test_host_cell_does_not_confuse_marker_1_with_marker_10():
    outer = [["a", "[칸 안의 표 10]"], ["b", "[칸 안의 표 1]"]]
    assert host_cell(outer, 1) == {"row": 1, "col": 1}


def test_titled_gives_the_host_cell_and_names_the_outer_table():
    inner = InnerTables()
    inner.add([["x", "y"], ["1", "2"]], [], InnerTables(), None)
    outer = [["구분", "내용"], ["설명", "[칸 안의 표 1]"]]

    [(rows, _spans, _deeper, title, host)] = inner.titled(outer, outer_title="[표 3]")

    assert rows == [["x", "y"], ["1", "2"]]
    assert title == "[칸 안의 표 1] [표 3]의 '설명' 행 '내용' 열 칸에 든 표"
    assert host == {"row": 1, "col": 1}
