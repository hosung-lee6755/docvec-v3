"""제목 상자 표를 제목으로 읽기(2026-11-17).

공공 문서는 장 제목과 세부사업 이름을 한 줄짜리 표에 넣어 꾸미는 일이 많다.

    [표 5]                      [표 10]
    Ⅰ |  | 사업 개요            ① | 조사료 사일리지 제조·운송비 지원

이것을 표로만 두면 제목 구조에서 빠져, 그 아래의 "1. 사업대상자"가 어느 사업의 것인지 알 수 없다.
여기서는 줄이 하나뿐인 짧은 표 가운데 다음 셋만 제목으로 본다.

- 번호 표시로 시작하는 상자("① | 조사료…", "Ⅱ. 사업 내용")
- 붙임·참고 표시로 시작하는 상자("참고1 | 법령체계 개편(안)", "붙임 1 | 신청자격 확인서"). 부록 묶음이므로 맨 윗단계다
- 번호 없이 한 문구만 든 표어 상자(" | 제명을 바꾼다! (…)"). 보도자료가 절을 나누는 방식이다(2026-11-24)

번호 없이 기관 이름만 든 상자(흐름도의 "농림축산식품부" 같은 것)는 제목이 아니므로 표로 둔다. 표어 상자도 낱말이
셋 이상이거나 느낌표로 끝나야 하고, 문장으로 끝나거나 글머리표·여러 문단이 든 상자는 강조 글이므로 표로 둔다.

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
# 붙임·참고 표시: "참고1", "붙임 1", "<별첨 2>", "【참고 3】". 뒤에 제목이 이어져도 된다
_ANNEX_RE = re.compile(r"^[<〈《【\[(]?\s*(?:참고|붙임|별첨|별표|별지|첨부|부록)\s*\d{0,2}\s*[>〉》】\])]?(?:\s|$)")
# 표어 상자에서 받지 않는 것: 문장 끝, 글머리표, 괄호로 감싼 소제목 표시("< 부적격 사항 >")
_SENTENCE_END_RE = re.compile(r"(?:다|요|함|음|임|됨|것)\.?$|\.$")
_BULLET_START_RE = re.compile(r"^[◈󰋮▷▶▪•‣※☞○●◦\-*·]")
_WRAPPED_RE = re.compile(r"^[<〈《\[【].*[>〉》\]】]$")
_HANGUL_RE = re.compile(r"[가-힣]")
# 칸 안 문단 구분(hwp_adapter.CELL_PARAGRAPH_SEP). 문단이 여럿이면 제목이 아니다
_CELL_PARAGRAPH_SEP = " / "
SLOGAN_MIN_WORDS = 3
_CELL_SEPARATOR = " | "
TITLE_BOX_MAX_CELLS = 3
ROMAN_LEVEL = 1
OTHER_LEVEL = 2
# 표어 상자는 그 아래 □ 줄 제목을 묶는 절 제목이다
SLOGAN_LEVEL = 1


def starts_with_roman(line: str) -> bool:
    return bool(_ROMAN_START_RE.match(line.strip()))


def title_box_heading(
    table_lines: list[str], max_chars: int, allow_slogan: bool = True
) -> tuple[str, int] | None:
    """표 블록의 줄들("[표 N]"과 그 아래 줄)이 제목 상자면 (제목 글, 수준)을 돌려준다.

    allow_slogan 이 거짓이면 번호 없는 표어 상자는 제목으로 보지 않는다. 번호·붙임 제목 상자로 장을 나눈 문서에서
    한 칸 상자는 장 안의 주체 표시("시·도(시·군), 농협경제지주…")라 1단계 제목으로 올리면 장 밖으로 튀어나온다."""
    if len(table_lines) != 2:
        return None
    cells = [cell.strip() for cell in table_lines[1].split(_CELL_SEPARATOR)]
    filled = [cell for cell in cells if cell]
    if not filled or len(filled) > TITLE_BOX_MAX_CELLS:
        return None
    title = " ".join(filled)
    if len(title) > max_chars:
        return None
    if _ANNEX_RE.match(filled[0]):
        return title, ROMAN_LEVEL
    marker_alone = len(filled) >= 2 and _MARKER_CELL_RE.match(filled[0])
    if marker_alone or _MARKED_TEXT_RE.match(filled[0]):
        return title, ROMAN_LEVEL if filled[0][0] in _ROMAN else OTHER_LEVEL
    if allow_slogan and len(filled) == 1 and _is_slogan(filled[0]):
        return title, SLOGAN_LEVEL
    return None


def _is_slogan(text: str) -> bool:
    """번호 없는 한 칸 상자가 절 제목 구실을 하는 표어인지."""
    if _CELL_PARAGRAPH_SEP in text or _BULLET_START_RE.match(text) or _WRAPPED_RE.match(text):
        return False
    if not _HANGUL_RE.search(text):
        return False
    if text.endswith("!"):
        return True
    return len(text.split()) >= SLOGAN_MIN_WORDS and not _SENTENCE_END_RE.search(text)


def shifted_level(level: int | None, shift: int, max_level: int | None) -> int | None:
    """제목 상자 아래의 줄 제목 수준. 원래 제목으로 남던 것(max_level 이하)은 내린 뒤에도 제목으로 남긴다."""
    if level is None or not shift:
        return level
    shifted = level + shift
    if max_level and level <= max_level:
        return min(shifted, max_level)
    return shifted
