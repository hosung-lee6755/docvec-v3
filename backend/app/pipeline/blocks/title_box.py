"""제목 상자 표를 제목으로 읽기(2026-11-17).

공공 문서는 장 제목과 세부사업 이름을 한 줄짜리 표에 넣어 꾸미는 일이 많다.

    [표 5]                      [표 10]
    Ⅰ |  | 사업 개요            ① | 조사료 사일리지 제조·운송비 지원

이것을 표로만 두면 제목 구조에서 빠져, 그 아래의 "1. 사업대상자"가 어느 사업의 것인지 알 수 없다.
여기서는 줄이 하나뿐이고 번호 표시로 시작하는 짧은 표만 제목으로 본다. 번호 없이 기관 이름만 든 상자
(흐름도의 "농림축산식품부" 같은 것)는 제목이 아니므로 표로 둔다.

제목 상자는 줄 안의 번호 제목("1. 사업대상자")보다 윗단계다. 그래서 제목 상자가 나온 뒤의 줄 제목은
그 상자의 수준만큼 아래로 내린다(shifted_level). 줄 제목이 로마 숫자로 시작하면 다시 맨 윗단계로 본다.
"""
import re

_ROMAN = "ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ"
_CIRCLED = "①-⑳"
# 번호 표시만 든 칸: "①", "Ⅱ", "3."
_MARKER_CELL_RE = re.compile(rf"^(?:[{_CIRCLED}]|[{_ROMAN}]{{1,4}}\.?|\d{{1,2}}\.)$")
# 번호 표시로 시작하는 글: "① 조사료…", "Ⅱ. 사업 내용", "1. 조사료 생산"
_MARKED_TEXT_RE = re.compile(rf"^(?:[{_CIRCLED}]\s*|[{_ROMAN}]{{1,4}}[.\s]\s*|\d{{1,2}}\.\s+)\S")
_ROMAN_START_RE = re.compile(rf"^[{_ROMAN}]{{1,4}}[.\s]")
_CELL_SEPARATOR = " | "
TITLE_BOX_MAX_CELLS = 3
ROMAN_LEVEL = 1
OTHER_LEVEL = 2


def starts_with_roman(line: str) -> bool:
    return bool(_ROMAN_START_RE.match(line.strip()))


def title_box_heading(table_lines: list[str], max_chars: int) -> tuple[str, int] | None:
    """표 블록의 줄들("[표 N]"과 그 아래 줄)이 제목 상자면 (제목 글, 수준)을 돌려준다."""
    if len(table_lines) != 2:
        return None
    cells = [cell.strip() for cell in table_lines[1].split(_CELL_SEPARATOR)]
    filled = [cell for cell in cells if cell]
    if not filled or len(filled) > TITLE_BOX_MAX_CELLS:
        return None
    marker_alone = len(filled) >= 2 and _MARKER_CELL_RE.match(filled[0])
    if not marker_alone and not _MARKED_TEXT_RE.match(filled[0]):
        return None
    title = " ".join(filled)
    if len(title) > max_chars:
        return None
    return title, ROMAN_LEVEL if filled[0][0] in _ROMAN else OTHER_LEVEL


def shifted_level(level: int | None, shift: int, max_level: int | None) -> int | None:
    """제목 상자 아래의 줄 제목 수준. 원래 제목으로 남던 것(max_level 이하)은 내린 뒤에도 제목으로 남긴다."""
    if level is None or not shift:
        return level
    shifted = level + shift
    if max_level and level <= max_level:
        return min(shifted, max_level)
    return shifted
