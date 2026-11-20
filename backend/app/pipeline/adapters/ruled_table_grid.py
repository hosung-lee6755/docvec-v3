"""선으로 그린 표(pdfplumber Table)의 칸 위치로 합친 칸을 알아내 격자를 만든다.

pdfplumber 의 extract() 는 합친 칸의 글을 첫 자리에만 두고 나머지를 None 으로 둔다. 그래서 세로로 합친 칸
("구 분"이 두 줄에 걸친 경우)의 아랫줄이 비고, 두 줄짜리 머리글의 윗줄("NS형")이 아랫줄 세 칸
("마찰클러치형", "클러치일체형", "전자클러치형")과 이어지지 않았다(KR S-03010 표 2, 2026-11-20).
- 세로로 합친 칸은 걸친 줄마다 글을 둔다.
- 가로로 합친 칸도 걸친 열마다 글을 둔다. 원본에서 "1Φ220V AC"는 NS형 세 종류 모두의 사용전원인데, 첫 열에만
  두면 나머지 두 종류의 값이 빈칸으로 읽혔다(사용자 지적, 2026-11-20). 선으로 그린 표는 열이 실제 선이라
  Docling 표처럼 열이 잘못 늘어나 같은 글이 일곱 번 복사되는 일이 없다. 표 폭의 절반보다 넓은 칸(설명, 중간 제목)은 첫 열에만 둔다.
- 글이 시작되는 칸이 하나도 없는 열(장식 선이 만든 열)은 채우기 전에 뺀다. 그래야 가로 채우기가 빈 열로 번지지 않는다.
- 맨 윗줄 칸이 여러 줄에 걸치고 그 아래 열이 나뉘면 머리글이 여러 줄이다. 열마다 위에서 아래로 이어 붙여 한 줄로 만든다.
합친 칸 위치는 spans 로 남겨 표 탭이 원본처럼 칸을 합쳐 보여 준다.
"""
from __future__ import annotations

from pdfplumber.table import Table

# 칸 경계 좌표를 같은 값으로 볼 때 반올림하는 자리(pt 소수 첫째 자리)
_COORD_DIGITS = 1
# 가로로 합친 칸은 표 폭의 이 비율 이하에 걸칠 때만 열마다 채운다. 더 넓은 칸은 설명·중간 제목이라 첫 열에만 둔다
# (디에스아이 진단요약서의 "시설 투자 및 운용방법 개선을 통해 절감"이 열 개 넘는 열에 되풀이됐다)
MAX_FILL_SHARE = 0.5
# 이보다 많은 줄을 머리글로 보지 않는다(docling_adapter 와 같다)
MAX_HEADER_ROWS = 3

Cell = tuple[int, int, int, int, str]


def _cell_texts(table: Table, extra: dict[tuple, str] | None = None) -> dict[tuple, str]:
    """칸 bbox → 글. extract() 의 자리는 table.rows[i].cells[j] 와 같은 순서다.
    extra 는 칸 글 뒤에 덧붙일 글이다(칸 안에서 떼어 낸 표의 "[칸 안의 표 k]" 표시)."""
    extra = extra or {}
    texts: dict[tuple, str] = {}
    for row, row_texts in zip(table.rows, table.extract()):
        for cell, text in zip(row.cells, row_texts):
            if cell is not None:
                box = tuple(cell)
                texts[box] = " ".join(part for part in ((text or "").strip(), extra.get(box, "")) if part)
    return texts


def _span(start: float, end: float, starts: list[float]) -> tuple[int, int]:
    first = starts.index(round(start, _COORD_DIGITS))
    count = sum(1 for value in starts if round(start, _COORD_DIGITS) <= value < round(end, _COORD_DIGITS))
    return first, max(count, 1)


def grid_cells(table: Table, extra: dict[tuple, str] | None = None) -> list[Cell]:
    """(줄, 열, 줄 수, 열 수, 글) 목록. 열은 칸 왼쪽 x, 줄은 칸 위쪽 y 의 서로 다른 값으로 센다(pdfplumber 와 같다)."""
    boxes = [tuple(c) for c in table.cells]
    if not boxes:
        return []
    texts = _cell_texts(table, extra)
    xs = sorted({round(box[0], _COORD_DIGITS) for box in boxes})
    ys = sorted({round(box[1], _COORD_DIGITS) for box in boxes})
    cells: list[Cell] = []
    for box in boxes:
        col, col_span = _span(box[0], box[2], xs)
        row, row_span = _span(box[1], box[3], ys)
        cells.append((row, col, row_span, col_span, texts.get(box, "")))
    return cells


def _without_ghost_columns(cells: list[Cell]) -> list[Cell]:
    """글이 시작되는 칸이 하나도 없는 열을 빼고 열 번호와 열 수를 당긴다. 그 열에만 있는 빈 칸은 버린다."""
    width = max(col + col_span for _, col, _, col_span, _ in cells)
    origin_cols = {col for _, col, _, _, text in cells if text}
    kept = [c for c in range(width) if c in origin_cols]
    if len(kept) == width:
        return cells
    new_index = {old: new for new, old in enumerate(kept)}
    trimmed: list[Cell] = []
    for row, col, row_span, col_span, text in cells:
        covered = [new_index[c] for c in range(col, col + col_span) if c in new_index]
        if covered:
            trimmed.append((row, covered[0], row_span, len(covered), text))
    return trimmed


def _fill_grid(cells: list[Cell]) -> tuple[list[list[str]], list[dict]]:
    """합친 칸은 걸친 줄과 열마다 글을 둔다(표 폭의 절반보다 넓은 칸은 첫 열에만). 글이 시작되는 칸이 하나도 없는 줄은 뺀다.

    다른 열의 가는 선 때문에 생긴 격자 줄은 합친 칸 글만 되풀이하게 된다(자율형공장 공고 15쪽 "정부일반형
    스마트공장"이 세 번 나왔다). 그런 줄은 원래 표에 없는 줄이다."""
    height = max(row + row_span for row, _, row_span, _, _ in cells)
    width = max(col + col_span for _, col, _, col_span, _ in cells)
    grid = [["" for _ in range(width)] for _ in range(height)]
    origins: set[int] = set()
    spans: list[dict] = []
    for row, col, row_span, col_span, text in cells:
        if text:
            origins.add(row)
        filled_cols = range(col, col + col_span) if col_span <= width * MAX_FILL_SHARE else [col]
        for offset in range(row_span):
            for target in filled_cols:
                grid[row + offset][target] = text
        if row_span > 1 or col_span > 1:
            spans.append({"row": row, "col": col, "row_span": row_span, "col_span": col_span})
    kept = sorted(origins)
    new_index = {old: new for new, old in enumerate(kept)}
    adjusted: list[dict] = []
    for span in spans:
        covered = [new_index[r] for r in range(span["row"], span["row"] + span["row_span"]) if r in new_index]
        if covered and (len(covered) > 1 or span["col_span"] > 1):
            adjusted.append({**span, "row": covered[0], "row_span": len(covered)})
    return [grid[index] for index in kept], adjusted


def header_row_count(cells: list[Cell]) -> int:
    """맨 윗줄 칸 중 하나가 여러 줄에 걸치고(구 분), 다른 하나가 여러 열에 걸치면(NS형) 그 줄 수만큼이 머리글이다."""
    first = [c for c in cells if c[0] == 0]
    depth = max((c[2] for c in first), default=1)
    if 2 <= depth <= MAX_HEADER_ROWS and any(c[3] > 1 for c in first):
        return depth
    return 1


def _merged_header(cells: list[Cell]) -> list[str]:
    width = max(col + col_span for _, col, _, col_span, _ in cells)
    parts: list[list[str]] = [[] for _ in range(width)]
    for _, col, _, col_span, text in sorted(cells):
        for index in range(col, col + col_span):
            if text and text not in parts[index]:
                parts[index].append(text)
    return [" ".join(part) for part in parts]


def merged_cell_grid(table: Table, extra: dict[tuple, str] | None = None) -> tuple[list[list[str]], list[dict]]:
    """격자 행과 합친 칸 목록(spans: row, col, row_span, col_span). 글이 없는 줄은 뺀다."""
    cells = grid_cells(table, extra)
    if not cells:
        return [], []
    cells = _without_ghost_columns(cells)
    if not cells:
        return [], []  # 글이 하나도 없는 틀
    depth = header_row_count(cells)
    body = [(row - depth, col, row_span, col_span, text) for row, col, row_span, col_span, text in cells if row >= depth]
    # 본문이 빈 서식 표(기계설비 매뉴얼 455쪽 신청 대장)는 머리글을 합치면 한 줄만 남아 표로 보지 않게 된다.
    # 그런 표는 머리글 줄을 그대로 둔다
    if depth < 2 or not any(text for *_, text in body):
        return _fill_grid(cells)
    header = _merged_header([c for c in cells if c[0] < depth])
    body_rows, body_spans = _fill_grid(body)
    width = max(len(header), *(len(r) for r in body_rows)) if body_rows else len(header)
    rows = [header + [""] * (width - len(header)), *(r + [""] * (width - len(r)) for r in body_rows)]
    return rows, [{**span, "row": span["row"] + 1} for span in body_spans]
