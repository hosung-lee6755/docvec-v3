"""합친 칸 채우기 규칙(2026-11-25). 형식마다 달랐던 규칙을 하나로 맞춘다.

세로로 합친 칸은 걸친 줄마다 글을 둔다. 가로로 합친 칸은 첫 열이 아닌 본문 칸이고, 표 폭의 절반 이하에 걸치며,
위 머리글이 그 구간을 서로 다른 열로 나눌 때만 열마다 둔다. 나머지는 첫 열에만 둔다.
"""
from app.pipeline.adapters.table_merge import fill_columns


def test_value_under_distinct_header_columns_fills_each_column():
    # KR S-03010 표 2: "220V" 는 NS형 세 종류 모두의 값이다(사용자 지적, 2026-11-20)
    cells = [
        (0, 0, 1, 1, "Item"), (0, 1, 1, 1, "Friction"), (0, 2, 1, 1, "Integral"), (0, 3, 1, 1, "Magnetic"),
        (0, 4, 1, 1, "MJ"), (0, 5, 1, 1, "Note"),
        (1, 0, 1, 1, "Power"), (1, 1, 1, 3, "220V"), (1, 4, 1, 1, "380V"), (1, 5, 1, 1, ""),
    ]

    assert list(fill_columns(cells[7], cells, width=6)) == [1, 2, 3]


def test_row_label_spanning_label_columns_is_written_once():
    # d5 제안서 "직접인건비 소계"(2026-11-24): 행 이름 칸은 되풀이하지 않는다
    cells = [(0, 0, 1, 1, "구분"), (0, 1, 1, 1, "인원"), (0, 2, 1, 1, "금액"), (1, 0, 1, 2, "소계"), (1, 2, 1, 1, "100")]

    assert list(fill_columns(cells[3], cells, width=3)) == [0]


def test_cell_under_a_header_merged_the_same_way_is_written_once():
    # 법령심사 문서 승인 표: 머리글 "소속"이 두 격자 열을 합친 칸이면 그 아래 "에쓰오씨소프트"도 한 열이다
    cells = [(0, 0, 1, 1, "구분"), (0, 1, 1, 2, "소속"), (0, 3, 1, 1, "이름"),
             (1, 0, 1, 1, "작성"), (1, 1, 1, 2, "에쓰오씨소프트"), (1, 3, 1, 1, "이호성")]

    assert list(fill_columns(cells[4], cells, width=4)) == [1]
    assert list(fill_columns(cells[1], cells, width=4)) == [1]


def test_wide_note_rows_are_written_once():
    cells = [(0, c, 1, 1, f"H{c}") for c in range(4)] + [(1, 1, 1, 3, "설명 문장")]

    assert list(fill_columns(cells[-1], cells, width=4)) == [1]


def test_two_row_header_is_looked_up_above_the_body():
    # 머리글이 두 줄(윗줄 "NS" 가 세 열에 걸치고 아랫줄이 셋으로 나뉨)이면 아랫줄로 판단한다
    cells = [
        (0, 0, 2, 1, "Item"), (0, 1, 1, 3, "NS"), (0, 4, 2, 1, "MJ"), (0, 5, 2, 1, "Note"),
        (1, 1, 1, 1, "Friction"), (1, 2, 1, 1, "Integral"), (1, 3, 1, 1, "Magnetic"),
        (2, 0, 1, 1, "Power"), (2, 1, 1, 3, "220V"),
        (3, 0, 1, 1, "Weight"), (3, 1, 1, 1, "1"), (3, 2, 1, 1, "2"), (3, 3, 1, 1, "3"),
    ]

    assert list(fill_columns(cells[8], cells, width=6)) == [1, 2, 3]
