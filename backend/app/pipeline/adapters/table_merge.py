"""합친 칸의 글을 격자의 어느 자리에 둘지 정하는 공용 규칙(2026-11-25).

예전에는 형식마다 규칙이 달랐다. HWP, HWPX, DOCX, Docling 표는 가로로 합친 칸을 첫 열에만 두었고, PDF 선 표는
표 폭의 절반 이하면 열마다 두었으며, 그림에서 읽은 표와 pdfplumber 표는 합친 칸 목록(spans)조차 없었다.
그래서 같은 모양의 표가 문서마다 "구분 | 구분"처럼 겹치거나 빈칸으로 나왔다(사용자 지적, 2026-11-25).

규칙은 하나다.
- 세로로 합친 칸은 걸친 줄마다 글을 둔다. RAG 청크의 표 행마다 그 행의 맥락(행 이름)이 남는다.
- 가로로 합친 칸은 다음을 모두 만족할 때만 걸친 열마다 글을 둔다. 첫 열(행 이름 자리)이 아니고, 표 폭의 절반
  이하에 걸치며, 위 머리글 줄이 그 구간을 서로 다른 두 칸 이상으로 나눈다. 원본에서 "1Φ220V AC"는 NS형 세 종류
  모두의 값이라 열마다 있어야 하고(2026-11-20), "직접인건비 소계"나 머리글 "소속"과 같은 폭으로 합친 "에쓰오씨소프트"는
  한 칸이라 한 번만 적어야 한다(2026-11-24, 2026-11-25).
화면은 spans 로 원본처럼 칸을 합쳐 그린다.
"""
from __future__ import annotations

Cell = tuple[int, int, int, int, str]

# 가로로 합친 칸은 표 폭의 이 비율 이하에 걸칠 때만 열마다 채운다. 더 넓은 칸은 설명이나 중간 제목이다
MAX_FILL_SHARE = 0.5
# 표 맨 위에서 이만큼의 줄을 머리글 후보로 본다
HEADER_LOOKUP_ROWS = 3


def _covering(cells: list[Cell], row: int, col: int) -> int | None:
    for index, (r, c, row_span, col_span, _) in enumerate(cells):
        if r <= row < r + row_span and c <= col < c + col_span:
            return index
    return None


def _header_splits(cells: list[Cell], cell: Cell) -> bool:
    """셀 위 머리글 줄 하나가 셀이 걸친 열을 글 있는 서로 다른 칸 둘 이상으로 나누는가."""
    row, col, _, col_span, _ = cell
    top_rows = sorted({r for r, *_ in cells})[:HEADER_LOOKUP_ROWS]
    for header_row in (r for r in top_rows if r < row):
        owners = {_covering(cells, header_row, c) for c in range(col, col + col_span)}
        filled = {owner for owner in owners if owner is not None and cells[owner][4].strip()}
        if len(filled) >= 2:
            return True
    return False


def fill_columns(cell: Cell, cells: list[Cell], width: int) -> range | list[int]:
    """합친 칸의 글을 둘 열 번호들. cells 는 같은 표의 모든 칸(머리글 칸 포함)이다."""
    _, col, _, col_span, _ = cell
    if col_span <= 1 or col == 0 or col_span > width * MAX_FILL_SHARE or not _header_splits(cells, cell):
        return [col]
    return range(col, col + col_span)
