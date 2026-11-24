"""표 영역 안 원본 글자 줄이 표 글에서 빠졌는지 보고, 빠진 줄을 칸 좌표로 되돌려 넣는다(2026-11-23).

PDF가 아닌 형식까지 원본과 대조하면서(quality_check 1.11.0) 표 칸 글이 통째로 빠지는 경우가 드러났다.
- Docling 표 구조 모델이 칸 안의 한 줄을 어느 칸에도 넣지 않았다(자율형공장 공고 17쪽, 위 칸과 아래 칸 사이에 낀 줄).
- 바깥 세로 테두리가 없는 선 표는 양 끝 열이 칸으로 잡히지 않아 그 열 글이 모두 빠졌다(UIUX 가이드라인 80쪽).
표 하나를 어떻게 읽었든 표 영역의 원본 글자 줄과 견주면 빠진 줄을 알 수 있다. 어댑터는 이것으로 두 표 결과 가운데
덜 빠뜨린 쪽을 고르고, 남은 줄은 가장 가까운 칸에 붙인다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

Box = tuple[float, float, float, float]  # 위쪽 원점 (x0, top, x1, bottom)

# 이 비율 이상의 낱말이 표 글에 없으면 그 줄이 빠진 것으로 본다. 여러 칸이 한 줄로 읽힌 숫자 줄은 낱말이 다 있다
MISSING_WORD_SHARE = 0.5
# 빠진 줄을 붙일 칸은 줄 높이의 이 배수 안에 있어야 한다. 더 멀면 어느 칸 글인지 모르므로 붙이지 않는다
MAX_GAP_IN_LINE_HEIGHTS = 2.0
# 줄과 칸이 가로로 이만큼(둘 중 좁은 폭에 대한 비율) 겹쳐야 같은 열로 본다
MIN_HORIZONTAL_OVERLAP = 0.5

_NON_WORD_RE = re.compile(r"[^0-9A-Za-z가-힣]+")
_WORD_CHARS_RE = re.compile(r"[0-9A-Za-z가-힣]")


@dataclass(frozen=True)
class TextLine:
    text: str
    box: Box


def lines_from_words(words: list[tuple]) -> list[TextLine]:
    """PyMuPDF get_text("words") 결과를 (블록, 줄)마다 묶어 읽는 순서(위에서 아래, 왼쪽에서 오른쪽)로 돌려준다."""
    grouped: dict[tuple, list[tuple]] = {}
    for word in words:
        grouped.setdefault((word[5], word[6]), []).append(word)
    lines = [
        TextLine(
            " ".join(w[4] for w in sorted(group, key=lambda w: w[0])),
            (min(w[0] for w in group), min(w[1] for w in group), max(w[2] for w in group), max(w[3] for w in group)),
        )
        for group in grouped.values()
    ]
    return sorted(lines, key=lambda line: (line.box[1], line.box[0]))


def _flat(text: str) -> str:
    # 글자와 숫자만 견준다. 세원화성 진단보고서 34쪽은 글자 층에 "가격원"만 있고 괄호는 따로 그려져 있어,
    # 기호까지 견주면 Docling 칸 글 "가격 (원)"이 있는데도 빠진 줄로 보고 한 번 더 붙였다(2026-11-23)
    return _NON_WORD_RE.sub("", text)


def _is_word(token: str) -> bool:
    return len(_WORD_CHARS_RE.findall(token)) >= 2


def missing_lines(lines: list[TextLine], table_texts: list[str]) -> list[TextLine]:
    """표 글(칸 글, 제목)에 없는 원본 줄. 띄어쓰기와 기호는 보지 않는다(Docling 칸 글은 띄어쓰기가 빠지기도 하고,
    글자 층은 괄호를 따로 그리기도 한다)."""
    flat = "".join(_flat(text) for text in table_texts)
    missing = []
    for line in lines:
        words = [token for token in line.text.split() if _is_word(token)]
        if not words or _flat(line.text) in flat:
            continue
        absent = [word for word in words if _flat(word) not in flat]
        if len(absent) >= len(words) * MISSING_WORD_SHARE:
            missing.append(line)
    return missing


def _horizontal_overlap(line: Box, cell: Box) -> float:
    overlap = min(line[2], cell[2]) - max(line[0], cell[0])
    narrower = min(line[2] - line[0], cell[2] - cell[0])
    return overlap / narrower if narrower > 0 else 0.0


def _vertical_gap(line: Box, cell: Box) -> float:
    center = (line[1] + line[3]) / 2
    if cell[1] <= center <= cell[3]:
        return 0.0
    return max(cell[1] - line[3], line[1] - cell[3], 0.0)


def _best_cell(line: TextLine, boxes: list[Box | None]) -> int | None:
    height = max(line.box[3] - line.box[1], 1.0)
    candidates = []
    for index, box in enumerate(boxes):
        if box is None or _horizontal_overlap(line.box, box) < MIN_HORIZONTAL_OVERLAP:
            continue
        gap = _vertical_gap(line.box, box)
        if gap > height * MAX_GAP_IN_LINE_HEIGHTS:
            continue
        # 거리가 같으면 위 칸에 붙인다. 칸 안 글머리 목록의 다음 줄이 칸 아래로 비어져 나온 경우가 많다
        is_below = box[1] >= line.box[3]
        candidates.append((gap, is_below, box[1], index))
    return min(candidates)[3] if candidates else None


def refill_cells(boxes: list[Box | None], texts: list[str], lines: list[TextLine]) -> list[str]:
    """빠진 줄을 같은 열에서 가장 가까운 칸 글 뒤에 붙인 새 칸 글 목록. 붙일 칸이 없는 줄은 버린다."""
    filled = list(texts)
    for line in lines:
        index = _best_cell(line, boxes)
        if index is not None:
            filled[index] = f"{filled[index]} {line.text}".strip()
    return filled
