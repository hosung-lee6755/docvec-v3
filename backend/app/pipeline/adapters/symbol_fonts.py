"""기호 글꼴(Wingdings, Symbol) 글자를 화면에 보이는 유니코드 글자로 적는다(2026-11-26).

문서는 기호 글꼴의 글자를 사용자 영역 코드(U+F020~U+F0FF, 글꼴 안 코드 + 0xF000)로 저장한다. 이 코드는 그 글꼴로
그려야만 모양이 있어, 그대로 두면 파싱 본문·RAG 청크·원문 대조 화면에서 빈칸이나 네모로 보였다.

어느 글꼴의 글자인지 알 때만 바꾼다. PDF 는 글자마다 글꼴 이름이 있고(내장 글꼴의 실제 이름 포함), PPTX 는 글자
묶음의 sym 글꼴이 있다. 한글(HWP, HWPX)은 이 코드를 맑은 고딕 같은 보통 글꼴로 적어 두지만, 올린 문서 전체에서 쓰임새가
모두 Wingdings 였다("❑ 사업명", "❍ 세부", "절차 / ❶ 접속 → ❷ 선택"). 그래서 한글은 Symbol 글꼴이 아니면 Wingdings 로
읽는다(hancom_symbol_kind). 표에 없는 코드와 다른 사용자 영역 글자(PDF 수식 글꼴의 U+E0xx 등)는 그대로 둔다.
"""
from __future__ import annotations

SYMBOL_CODE_OFFSET = 0xF000
_FIRST_CODE, _LAST_CODE = 0x20, 0xFF

# Wingdings 글꼴 코드 → 유니코드. 기본 다국어 영역 글자로 모양과 뜻이 같은 것만 적는다
_WINGDINGS: dict[int, str] = {
    0x22: "✂", 0x23: "✁", 0x28: "☎", 0x29: "✆", 0x36: "⌛", 0x3E: "✇", 0x3F: "✍",
    0x41: "✌", 0x45: "☜", 0x46: "☞", 0x47: "☝", 0x48: "☟", 0x4A: "☺", 0x4C: "☹", 0x4E: "☠",
    0x51: "✈", 0x52: "☼", 0x54: "❄", 0x56: "✞", 0x58: "✠", 0x59: "✡", 0x5A: "☪", 0x5B: "☯", 0x5C: "ॐ",
    0x5D: "☸", 0x5E: "♈", 0x5F: "♉", 0x60: "♊", 0x61: "♋", 0x62: "♌", 0x63: "♍", 0x64: "♎", 0x65: "♏",
    0x66: "♐", 0x67: "♑", 0x68: "♒", 0x69: "♓",
    0x6C: "●", 0x6D: "❍", 0x6E: "■", 0x6F: "□", 0x70: "◻", 0x71: "❑", 0x72: "❒", 0x73: "⬧", 0x74: "⧫",
    0x75: "◆", 0x76: "❖", 0x77: "⬥", 0x78: "⌧", 0x7A: "⌘", 0x7B: "❀", 0x7C: "✿", 0x7D: "❝", 0x7E: "❞",
    0x80: "⓪", 0x81: "①", 0x82: "②", 0x83: "③", 0x84: "④", 0x85: "⑤", 0x86: "⑥", 0x87: "⑦", 0x88: "⑧",
    0x89: "⑨", 0x8A: "⑩", 0x8B: "⓿", 0x8C: "❶", 0x8D: "❷", 0x8E: "❸", 0x8F: "❹", 0x90: "❺", 0x91: "❻",
    0x92: "❼", 0x93: "❽", 0x94: "❾", 0x95: "❿",
    0x9E: "·", 0x9F: "•", 0xA0: "▪", 0xA1: "○", 0xA4: "◉", 0xA5: "◎", 0xA7: "▪", 0xA8: "◻",
    0xAA: "✦", 0xAB: "★", 0xAC: "✶", 0xAD: "✴", 0xAE: "✹", 0xAF: "✵", 0xB1: "⌖", 0xB2: "⟡", 0xB3: "⌑",
    0xB5: "✪", 0xB6: "✰", 0xD5: "⌫", 0xD6: "⌦", 0xD8: "➢", 0xE0: "➔", 0xE8: "➔",
    0xEF: "⇦", 0xF0: "⇨", 0xF1: "⇧", 0xF2: "⇩", 0xF3: "⬄", 0xF4: "⇳", 0xF5: "⬀", 0xF6: "⬁", 0xF7: "⬃",
    0xF8: "⬂", 0xF9: "▭", 0xFA: "▫", 0xFB: "✗", 0xFC: "✓", 0xFD: "☒", 0xFE: "☑",
}

_SYMBOL_LETTERS = dict(zip(
    "ABCDEFGHIKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
    "ΑΒΧΔΕΦΓΗΙΚΛΜΝΟΠΘΡΣΤΥςΩΞΨΖαβχδεφγηιϕκλμνοπθρστυϖωξψζ", strict=True,
))
# Symbol 글꼴 코드 → 유니코드(그리스 글자와 수학 기호)
_SYMBOL: dict[int, str] = {
    **{ord(code): char for code, char in _SYMBOL_LETTERS.items()},
    0x4A: "ϑ", 0x22: "∀", 0x24: "∃", 0x27: "∋", 0x2A: "∗", 0x2D: "−", 0x40: "≅", 0x5C: "∴", 0x5E: "⊥",
    0xA2: "′", 0xA3: "≤", 0xA5: "∞", 0xAC: "←", 0xAD: "↑", 0xAE: "→", 0xAF: "↓", 0xB0: "°", 0xB1: "±",
    0xB2: "″", 0xB3: "≥", 0xB4: "×", 0xB5: "∝", 0xB6: "∂", 0xB7: "•", 0xB8: "÷", 0xB9: "≠", 0xBA: "≡",
    0xBB: "≈", 0xC4: "⊗", 0xC5: "⊕", 0xC6: "∅", 0xC7: "∩", 0xC8: "∪", 0xCE: "∈", 0xCF: "∉", 0xD1: "∇",
    0xD5: "∏", 0xD6: "√", 0xD7: "⋅", 0xD8: "¬", 0xD9: "∧", 0xDA: "∨", 0xDB: "⇔", 0xDE: "⇒", 0xE5: "∑",
    0xF2: "∫",
}

_TABLES = {"wingdings": _WINGDINGS, "symbol": _SYMBOL}


def symbol_font_kind(font_name: str | None) -> str | None:
    """글꼴 이름이 표를 가진 기호 글꼴이면 그 종류("wingdings", "symbol"). 내장 글꼴 앞의 "ABCDEF+" 는 뗀다."""
    name = (font_name or "").split("+", 1)[-1].lower().replace("-", " ").replace("_", " ")
    words = name.split()
    if not words:
        return None
    if words[0] == "wingdings" and (len(words) == 1 or not words[1].isdigit()):
        return "wingdings"
    if words[0] in ("symbol", "symbolmt"):
        return "symbol"
    return None


def hancom_symbol_kind(font_names: list[str | None]) -> str:
    """한글 문서 글자의 기호 글꼴 종류. 글자 모양에 Symbol 이나 Wingdings 가 있으면 그것이고, 없으면 Wingdings 다."""
    for name in font_names:
        kind = symbol_font_kind(name)
        if kind:
            return kind
    return "wingdings"


def symbol_char(char: str, kind: str | None) -> str | None:
    """기호 글꼴 글자 하나(U+F020~F0FF, 또는 글꼴 코드 0x20~0xFF 를 바로 적은 글자)의 유니코드 글자. 모르면 None."""
    table = _TABLES.get(kind or "")
    if table is None or len(char) != 1:
        return None
    code = ord(char)
    if code >= SYMBOL_CODE_OFFSET:
        code -= SYMBOL_CODE_OFFSET
    if not _FIRST_CODE <= code <= _LAST_CODE:
        return None
    return table.get(code)


def is_symbol_code(char: str) -> bool:
    return SYMBOL_CODE_OFFSET + _FIRST_CODE <= ord(char) <= SYMBOL_CODE_OFFSET + _LAST_CODE


def with_symbol_font_chars(text: str, kind: str | None) -> str:
    """text 의 기호 글꼴 코드(U+F020~F0FF)를 화면 글자로 바꾼 새 글. 보통 글자와 표에 없는 코드는 그대로 둔다."""
    if not kind or not text or not any(is_symbol_code(ch) for ch in text):
        return text
    return "".join((symbol_char(ch, kind) or ch) if is_symbol_code(ch) else ch for ch in text)
