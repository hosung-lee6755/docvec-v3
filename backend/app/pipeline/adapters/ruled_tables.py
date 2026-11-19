"""PDF에 벡터 선으로 그린 표를 선 그대로 읽는다 (2026-11-17, 기계설비기술기준매뉴얼 표 실측).

Docling의 표 구조 모델은 칸 안에 들어 있는 작은 표의 선까지 바깥 표의 열로 펼친다. 실측한 문서에서는
4열 표가 10열이 되고 같은 글이 일곱 번 복사되었다. 이 문서의 표는 선이 정확히 그려져 있지만
바깥 왼쪽과 오른쪽 테두리 세로선이 없어 pdfplumber 기본 설정으로도 표가 잡히지 않았다.

여기서는
- 짧은 선(머리 장식 띠 같은 것)을 빼고,
- 가로선 여러 개가 같은 x에서 끝나면 그 자리에 빠진 테두리 세로선을 보충하고,
- 다른 표의 칸 안에 들어 있는 표는 바깥 표에서 떼어 따로 읽는다(바깥 칸 글에서도 뺀다).
Docling 어댑터는 Docling이 찾은 표와 위치가 겹치는 표가 여기 있으면 이 결과로 바꾼다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from pdfplumber.table import Table

from app.pipeline.adapters.pdf_adapter import _dedupe_tables, _table_iou

# 이보다 짧은 선은 표 선으로 보지 않는다(페이지 머리 장식 띠의 2pt 사각형 등)
MIN_EDGE_LENGTH = 15.0
# 칸이 다른 칸 안에 들어 있는지 볼 때 허용하는 오차(pt)
CONTAIN_TOLERANCE = 1.0
# 같은 x에서 끝나는 가로선이 이만큼 있어야 빠진 테두리 세로선으로 본다
MIN_ENDS_FOR_BORDER = 2
# 선이 이보다 많은 쪽(도면, 해칭)은 교차점 계산이 너무 오래 걸려 읽지 않는다. Docling 결과를 그대로 쓴다
MAX_EDGES_PER_ORIENTATION = 1500
# 가로선이 실제 세로선과 닿았다고 보는 거리(pt)
TOUCH_TOLERANCE = 2.0
# 표로 인정하는 최소 크기. 1열짜리나 내용 있는 행이 하나뿐인 틀은 글상자다
MIN_COLUMNS = 2
MIN_FILLED_ROWS = 2
# Docling 표와 같은 표로 보는 겹침 정도(IoU)
MATCH_IOU = 0.5

Bbox = tuple[float, float, float, float]


@dataclass(frozen=True)
class RuledTable:
    bbox: Bbox
    rows: list[list[str]]
    nested: tuple["RuledTable", ...] = ()
    # 표 맨 위의 칸 하나짜리 제목 줄("기계설비 착공 전 확인표"). rows에서는 뺀다
    title: str | None = None


def _contains(outer: Bbox, inner: Bbox) -> bool:
    return (
        outer != inner
        and inner[0] >= outer[0] - CONTAIN_TOLERANCE and inner[1] >= outer[1] - CONTAIN_TOLERANCE
        and inner[2] <= outer[2] + CONTAIN_TOLERANCE and inner[3] <= outer[3] + CONTAIN_TOLERANCE
    )


def _ruled_edges(page) -> tuple[list[dict], list[dict]]:
    horizontals = [e for e in page.edges if e["orientation"] == "h" and e["x1"] - e["x0"] >= MIN_EDGE_LENGTH]
    verticals = [e for e in page.edges if e["orientation"] == "v" and e["bottom"] - e["top"] >= MIN_EDGE_LENGTH]
    if len(horizontals) > MAX_EDGES_PER_ORIENTATION or len(verticals) > MAX_EDGES_PER_ORIENTATION:
        return [], []
    # 테두리는 표의 세로선과 닿는 가로선 끝에만 보충한다. 쪽 머리와 바닥 구분선은 세로선과 닿지 않으므로
    # 이 선들로 쪽 전체를 감싸는 가짜 표가 생기지 않는다(리뷰 지적)
    ends: dict[int, list[float]] = {}
    for edge in (h for h in horizontals if _touches_vertical(h, verticals)):
        for x in (round(edge["x0"]), round(edge["x1"])):
            ends.setdefault(x, []).append(edge["top"])
    borders = [
        {"x0": x, "x1": x, "top": min(tops), "bottom": max(tops), "orientation": "v",
         "width": 0, "height": max(tops) - min(tops), "object_type": "line"}
        for x, tops in ends.items()
        if len(tops) >= MIN_ENDS_FOR_BORDER and max(tops) > min(tops)
    ]
    return horizontals, verticals + borders


def _touches_vertical(horizontal: dict, verticals: list[dict]) -> bool:
    y = horizontal["top"]
    for vertical in verticals:
        if not horizontal["x0"] - TOUCH_TOLERANCE <= vertical["x0"] <= horizontal["x1"] + TOUCH_TOLERANCE:
            continue
        if vertical["top"] - TOUCH_TOLERANCE <= y <= vertical["bottom"] + TOUCH_TOLERANCE:
            return True
    return False


def _clean_rows(raw: list[list[str | None]]) -> list[list[str]]:
    rows = [[(cell or "").strip() for cell in row] for row in raw]
    split = [piece for row in rows for piece in _split_stacked_row(row)]
    return [row for row in split if any(row)]


# 한 칸에 이만큼 이상의 줄이 쌓였을 때만 가로 선 없는 여러 행으로 본다(두 줄은 긴 글이 접힌 경우가 많다)
MIN_STACKED_LINES = 3
# 숫자 하나(소수점은 한 번). 날짜("2024.01.05")와 절 번호("1.2.3")는 숫자 칸으로 보지 않는다
_NUMERIC_LINE_RE = re.compile(r"^[-−+]?\d[\d,]*(?:\.\d+)?%?$")
# 숫자 열이 하나뿐이면 다른 칸의 줄이 이만큼 짧을 때(공백 제외)만 나눈다. 긴 글이 마침 같은 줄 수로 접힌
# 경우를 피한다("750 초과 1500 이하"는 11자)
MAX_STACKED_LABEL_CHARS = 12


def _split_stacked_row(row: list[str]) -> list[list[str]]:
    """가로 선 없이 여러 행이 한 행으로 읽힌 경우를 줄마다 나눈다. 내용이 있는 칸이 모두 같은 줄 수이고,
    그중 한 칸이라도 줄마다 숫자 하나뿐이어야 한다(설계 외기온·습도 표 실측, 2026-11-19). 긴 글이 접힌 칸은
    줄 수가 칸마다 다르거나 숫자 열이 없어서 나누지 않는다."""
    lines = [[line.strip() for line in cell.split("\n") if line.strip()] if cell else [] for cell in row]
    filled = [cell_lines for cell_lines in lines if cell_lines]
    if len(filled) < 2:
        return [row]
    count = len(filled[0])
    if count < MIN_STACKED_LINES or any(len(cell_lines) != count for cell_lines in filled):
        return [row]
    numeric = [all(_NUMERIC_LINE_RE.match(line.replace(" ", "")) for line in cell_lines) for cell_lines in filled]
    if not any(numeric):
        return [row]
    labels_short = all(
        len(line.replace(" ", "")) <= MAX_STACKED_LABEL_CHARS
        for cell_lines, is_numeric in zip(filled, numeric) if not is_numeric for line in cell_lines
    )
    if sum(numeric) < 2 and not labels_short:
        return [row]
    return [[cell_lines[index] if cell_lines else "" for cell_lines in lines] for index in range(count)]


def _is_table(rows: list[list[str]]) -> bool:
    return len(rows) >= MIN_FILLED_ROWS and max((len(r) for r in rows), default=0) >= MIN_COLUMNS


def _split_title_row(rows: list[list[str]]) -> tuple[str | None, list[list[str]]]:
    """첫 행이 여러 열에 걸친 칸 하나뿐이면 표 제목이다. 그대로 두면 큰 표를 나눌 때 조각마다 머리 행 대신 반복된다."""
    filled = [cell for cell in rows[0] if cell] if rows else []
    if len(rows) >= MIN_FILLED_ROWS + 1 and len(rows[0]) >= MIN_COLUMNS and len(filled) == 1:
        return " ".join(filled[0].split()), rows[1:]
    return None, rows


def _without_chars_in(page, regions: list[Bbox]):
    if not regions:
        return page

    def keep(obj) -> bool:
        if obj.get("object_type") != "char":
            return True
        box = (obj["x0"], obj["top"], obj["x1"], obj["bottom"])
        return not any(_contains(region, box) for region in regions)

    return page.filter(keep)


def find_ruled_tables(page) -> list[RuledTable]:
    """쪽 하나에서 선으로 그린 표를 찾는다. 안쪽 표는 바깥 표의 nested로 붙는다."""
    horizontals, verticals = _ruled_edges(page)
    if len(horizontals) < 2 or len(verticals) < 2:
        return []
    settings = {
        "vertical_strategy": "explicit", "horizontal_strategy": "explicit",
        "explicit_vertical_lines": verticals, "explicit_horizontal_lines": horizontals,
    }
    found = _dedupe_tables(page.find_tables(settings), page.width * page.height)

    # (bbox, 바깥 칸, 안쪽 표 후보들) — 칸 안에 칸이 있으면 안쪽 칸들이 하나의 안쪽 표다
    groups: list[tuple[Bbox, list[tuple], list[Table]]] = []
    for table in found:
        cells = [tuple(c) for c in table.cells]
        inner = [c for c in cells if any(_contains(o, c) for o in cells)]
        outer = [c for c in cells if c not in inner]
        if not outer:
            continue
        groups.append((tuple(table.bbox), outer, [Table(page, inner)] if inner else []))

    # 다른 표의 영역 안에 통째로 들어 있는 표도 안쪽 표다
    standalone = [g for g in groups if not any(_contains(o[0], g[0]) for o in groups)]
    results: list[RuledTable] = []
    for bbox, outer_cells, inner_tables in standalone:
        inner_tables = inner_tables + [
            Table(page, cells) for other_bbox, cells, _ in groups if _contains(bbox, other_bbox)
        ]
        nested = tuple(
            RuledTable(bbox=tuple(t.bbox), rows=rows)
            for t in inner_tables
            if _is_table(rows := _clean_rows(t.extract()))
        )
        text_page = _without_chars_in(page, [t.bbox for t in nested])
        title, rows = _split_title_row(_clean_rows(Table(text_page, outer_cells).extract()))
        if _is_table(rows):
            results.append(RuledTable(bbox=bbox, rows=rows, nested=nested, title=title))
    return results


def match_ruled_table(tables: list[RuledTable], bbox: Bbox | None) -> RuledTable | None:
    """Docling 표 영역(위쪽 원점 좌표)과 가장 많이 겹치는 선 표. 충분히 겹치는 것이 없으면 None."""
    if bbox is None:
        return None
    best = max(tables, key=lambda t: _table_iou(t.bbox, bbox), default=None)
    if best is None or _table_iou(best.bbox, bbox) < MATCH_IOU:
        return None
    return best
