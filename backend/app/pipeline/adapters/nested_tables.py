"""칸 안의 표(안쪽 표)를 바깥 표와 잇는다(2026-11-20, NS-AM 검사매뉴얼 검토).

예전에는 형식마다 안쪽 표를 다르게 다뤘다. HWP, HWPX, HTML 은 안쪽 표의 칸 글을 바깥 칸 글에 이어 붙여
행과 열이 사라졌고, PDF 는 안쪽 표를 따로 냈지만 어느 칸에 있던 표인지 남기지 않았다.
이제 모든 형식이 같은 규칙을 따른다.
- 2행 2열 이상인 안쪽 표는 바깥 표 바로 뒤에 별도 표로 낸다. 한 줄이나 한 열짜리는 글상자라 칸 글로 둔다.
- 바깥 칸에는 안쪽 표가 있던 자리에 "[칸 안의 표 k]"를 남긴다. k 는 바깥 표 하나 안에서 매기는 번호다.
- 안쪽 표 제목은 같은 표시로 시작하고, 바깥 표 번호("[표 1]의")와 들어 있던 칸의 행 이름과 열 이름을 적는다.
- 안쪽 표는 parent_table_id(바깥 표 id)와 parent_cell(바깥 표 rows 기준 칸, 0부터)을 함께 남긴다. 글을 읽지 않고도
  프로그램이 표 B 에서 표 A 를 찾아갈 수 있게 하기 위해서다(2026-11-20).
- 칸 하나짜리 틀 안에 표만 들어 있으면 틀은 표가 아니다. 틀을 빼고 안쪽 표를 그 자리에 바로 낸다
  (R&D 스마트공장 공고의 추진체계도, 2021 조사료 지침의 시료 채취량 표).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_MARKER_FORMAT = "[칸 안의 표 {}]"
_MARKER_RE = re.compile(r"\[칸 안의 표 \d+\]")
# 행 이름과 열 이름은 이 글자 수까지만 쓴다. 긴 설명 칸이 제목을 덮지 않게 한다
MAX_LABEL_CHARS = 20
# 별도 표로 떼는 최소 크기. 이보다 작은 표는 칸 안의 글상자다(ruled_tables 의 표 인정 기준과 같다)
MIN_ROWS = 2
MIN_COLUMNS = 2


def nested_marker(index: int) -> str:
    return _MARKER_FORMAT.format(index)


def is_inner_table_title(title: str | None) -> bool:
    """칸 안에서 떼어 낸 표의 제목인가. 이런 표는 문서에서 바깥 표 바로 뒤에 있다."""
    return bool(title) and title.startswith(_MARKER_FORMAT.split("{")[0])


def strip_nested_markers(text: str) -> str:
    """원본 글과 맞춰 볼 때(미리보기 쪽 찾기) 표시를 뺀다."""
    return _MARKER_RE.sub("", text)


def is_separable_table(rows: list[list[str]]) -> bool:
    return len(rows) >= MIN_ROWS and max((len(row) for row in rows), default=0) >= MIN_COLUMNS


def is_frame_only(rows: list[list[str]]) -> bool:
    """칸 하나짜리 표에 안쪽 표 표시 말고 다른 글이 없으면 틀이다."""
    return len(rows) == 1 and len(rows[0]) == 1 and not re.sub(r"[\s/]", "", strip_nested_markers(rows[0][0]))


def _label(text: str) -> str:
    cleaned = " ".join(strip_nested_markers(text).replace(" / ", " ").split())
    return cleaned if len(cleaned) <= MAX_LABEL_CHARS else cleaned[:MAX_LABEL_CHARS] + "…"


def _host_cell(rows: list[list[str]], marker: str) -> tuple[int, int] | None:
    for row_index, row in enumerate(rows):
        for col_index, cell in enumerate(row):
            if marker in cell:
                return row_index, col_index
    return None


def _row_label(row: list[str], col: int) -> str:
    """안쪽 표가 든 칸보다 왼쪽에서 처음 나오는 글. 세로로 합친 칸이 같은 글로 채워져 있으면 건너뛴다."""
    host = row[col]
    return next((_label(cell) for cell in row[:col] if cell and cell != host and _label(cell)), "")


def _fills_the_row(row: list[str], col: int) -> bool:
    """칸이 한 줄 전체를 차지한다(같은 줄의 다른 칸이 비었거나 같은 글). 항목 아래의 설명 줄이 이렇다."""
    host = row[col]
    return not any(cell and cell != host for index, cell in enumerate(row) if index != col)


def _label_above(rows: list[list[str]], row: int) -> str:
    """바로 위에서 칸이 둘 이상 채워진 줄(항목 줄)의 첫 글."""
    for above in reversed(rows[:row]):
        filled = [cell for cell in above if cell]
        if len(set(filled)) >= 2:
            return _label(filled[0])
    return ""


def host_cell(outer_rows: list[list[str]], index: int) -> dict | None:
    """안쪽 표 k 가 들어 있던 바깥 표의 칸({"row", "col"}, 0부터). 표시를 찾지 못하면 None."""
    host = _host_cell(outer_rows, nested_marker(index))
    return {"row": host[0], "col": host[1]} if host else None


def _place(rows: list[list[str]], row: int, col: int) -> str:
    if _fills_the_row(rows[row], col):
        above = _label_above(rows, row)
        return f"'{above}' 행 아래 칸" if above else "칸"
    row_label = _row_label(rows[row], col)
    header = rows[0][col] if row > 0 and col < len(rows[0]) else ""
    col_label = _label(header) if header and header != rows[row][col] else ""
    if col_label == row_label:
        col_label = ""
    if row_label and col_label:
        return f"'{row_label}' 행 '{col_label}' 열 칸"
    if row_label:
        return f"'{row_label}' 행의 칸"
    if col_label:
        return f"'{col_label}' 열의 칸"
    return "칸"


def nested_table_title(
    outer_rows: list[list[str]], index: int, *, outer_title: str | None = None, name: str | None = None,
) -> str:
    """안쪽 표 제목. outer_rows 는 표시가 들어간 바깥 표, name 은 안쪽 표 자체의 캡션이다."""
    marker = nested_marker(index)
    host = _host_cell(outer_rows, marker)
    if host is None:
        where = "바로 위 표 안에 든 표"
    else:
        owner = f"{outer_title}의 " if outer_title else ""
        where = f"{owner}{_place(outer_rows, *host)}에 든 표"
    return f"{marker} {name} ({where})" if name else f"{marker} {where}"


@dataclass
class InnerTables:
    """표 하나의 칸 안에서 떼어 낸 안쪽 표들. 칸 글에는 그 자리에 "[칸 안의 표 k]"를 남긴다.
    항목은 (행, 합친 칸, 그 표의 칸 안에서 떼어 낸 표, 안쪽 표 캡션)이다."""

    found: list[tuple[list[list[str]], list[dict], InnerTables, str | None]] = field(default_factory=list)

    def add(self, rows: list[list[str]], spans: list[dict], deeper: InnerTables, caption: str | None) -> str:
        self.found.append((rows, spans, deeper, caption))
        return nested_marker(len(self.found))

    def titled(
        self, outer_rows: list[list[str]], outer_title: str | None = None,
    ) -> list[tuple[list[list[str]], list[dict], InnerTables, str, dict | None]]:
        """떼어 낸 순서대로 (행, 합친 칸, 그 안의 표, 제목, 들어 있던 칸). outer_rows 는 표시가 들어간 바깥 표,
        outer_title 은 제목에 적을 바깥 표 이름("[표 3]")이다."""
        return [
            (
                rows, spans, deeper,
                nested_table_title(outer_rows, number, outer_title=outer_title, name=caption),
                host_cell(outer_rows, number),
            )
            for number, (rows, spans, deeper, caption) in enumerate(self.found, start=1)
        ]
