"""요약 모델에 넘길 글의 금액을 원 단위 한국어 표기로 풀어 쓴다.

3B 요약 모델은 "7,500[천원]"(750만 원)을 "7500원"이나 "7,500만 원"으로 옮기고,
"9,000[백만원]"(90억 원)을 "9,000만원"으로 옮겼다. 프롬프트로 단위를 지시해도
나아지지 않았다(2026-11-21 실측). 그래서 모델이 단위를 계산할 일이 없도록 넘기기 전에
"750만 원", "90억 원"처럼 바꾼다. 모델이 그대로 옮기는 만원과 억원은 건드리지 않는다.

바꾸는 곳은 세 가지다.
- 본문의 숫자 바로 뒤 단위: "300백만원", "9,000 [백만원]", "0.5 (천원)"
- 표 머리글의 단위: "투자비 [백만원]" 열의 숫자 칸 전부
- 표 바로 위의 단위 안내: "(단위 : 백만원)" 다음 표의 숫자 칸 전부

저장된 본문은 바꾸지 않는다. 요약 입력에만 쓴다.
"""
import re
from decimal import ROUND_HALF_UP, Decimal

_UNIT = r"(천\s*만|백\s*만|천)\s*원"
_MULTIPLIER = {"천만": Decimal(10_000_000), "백만": Decimal(1_000_000), "천": Decimal(1_000)}
_NUMBER = r"(?<![\d.,])(-?\d[\d,]*(?:\.\d+)?)"
_INLINE = re.compile(
    _NUMBER + r"\s*(?:[\[(]\s*" + _UNIT + r"(?:/[^\])]*)?\s*[\])]|" + _UNIT + r")"
)
_HEADER_UNIT = re.compile(r"([\[(])\s*" + _UNIT + r"(/[^\])]*)?\s*([\])])")
_CAPTION = re.compile(r"^(\s*[\[(]?\s*단\s*위\s*[:：]\s*)" + _UNIT + r"(\s*[\])]?\s*)$")
_NUMERIC_CELL = re.compile(r"^(\s*)(-?\d[\d,]*(?:\.\d+)?)(\s*)$")
_SEPARATOR = re.compile(r"^\s*\|[\s:|-]+\|\s*$")
# 단위 안내와 표 사이에 표 제목 같은 줄이 끼는 경우까지만 이어 준다
_CAPTION_REACH = 2


def spell_out_money_units(text: str) -> str:
    return _INLINE.sub(_inline_replacement, _convert_tables(text))


def won_text(amount: Decimal) -> str:
    """원 금액을 "12억 3,456만 7,000원"처럼 적는다."""
    whole = int(amount.quantize(Decimal(1), rounding=ROUND_HALF_UP))
    sign, whole = ("-" if whole < 0 else ""), abs(whole)
    eok, rest = divmod(whole, 100_000_000)
    man, won = divmod(rest, 10_000)
    parts = [f"{value:,}{label}" for value, label in ((eok, "억"), (man, "만"), (won, "")) if value]
    if not parts:
        return "0원"
    return sign + " ".join(parts) + ("원" if won else " 원")


def _multiplier(unit: str) -> Decimal:
    return _MULTIPLIER[re.sub(r"\s", "", unit)]


def _to_won(number: str, unit: str) -> str:
    return won_text(Decimal(number.replace(",", "")) * _multiplier(unit))


def _inline_replacement(match: re.Match) -> str:
    return _to_won(match.group(1), match.group(2) or match.group(3))


def _is_table_row(line: str) -> bool:
    # HWP 계열 추출은 바깥 "|" 없이 "구 분 | 2015년 | 2016년"처럼 표를 적는다
    return line.lstrip().startswith("|") or line.count("|") >= 2


def _convert_tables(text: str) -> str:
    lines = text.split("\n")
    out: list[str] = []
    caption: re.Match | None = None
    caption_at = since_caption = 0
    index = 0
    while index < len(lines):
        line = lines[index]
        found = _CAPTION.match(line)
        if found:
            caption, caption_at, since_caption = found, len(out), 0
            out.append(line)
            index += 1
            continue
        if _is_table_row(line):
            end = index
            while end < len(lines) and _is_table_row(lines[end]):
                end += 1
            table, caption_used = _convert_table(lines[index:end], caption.group(2) if caption else None)
            out.extend(table)
            if caption_used:
                # 안내 문구는 숫자를 실제로 바꾼 표가 있을 때만 "원"으로 고친다
                out[caption_at] = f"{caption.group(1)}원{caption.group(3)}"
            caption, index = None, end
            continue
        if line.strip():
            since_caption += 1
            if since_caption > _CAPTION_REACH:
                caption = None
        out.append(line)
        index += 1
    return "\n".join(out)


def _inner_columns(cells: list[str], row: str) -> range:
    return range(1, len(cells) - 1) if row.lstrip().startswith("|") else range(len(cells))


def _header_units(cells: list[str], is_header: bool) -> dict[int, str]:
    """머리글 줄이거나 숫자 칸 없이 단위 표기가 있는 줄이면 열마다 단위를 돌려준다."""
    if not is_header and any(_NUMERIC_CELL.match(cell) for cell in cells):
        return {}
    return {column: found.group(2) for column, cell in enumerate(cells) if (found := _HEADER_UNIT.search(cell))}


def _convert_table(rows: list[str], caption_unit: str | None) -> tuple[list[str], bool]:
    """표의 숫자 칸을 원 표기로 바꾼다. 단위 안내를 실제로 썼는지도 함께 돌려준다.

    빈 줄 없이 붙은 표는 중간에 머리글 줄이 다시 나오므로, 숫자 없이 단위만 있는 줄을
    만날 때마다 그 줄을 새 머리글로 본다. 머리글이나 안내의 단위는 그 열에서 숫자를 하나라도
    바꿨을 때만 "원"으로 고친다. 숫자를 못 바꿨는데 단위만 "원"이 되면 원문보다 틀린 정보가 된다.
    """
    table = [row.split("|") for row in rows]
    column_units: dict[int, str] = {}
    header_at = -1
    converted: dict[int, set[int]] = {}
    caption_used = False
    for index, (row, cells) in enumerate(zip(rows, table)):
        if _SEPARATOR.match(row):
            continue
        # 첫 줄과 구분선 바로 위 줄은 숫자("2023")가 있어도 머리글이다
        is_header = index == 0 or (index + 1 < len(rows) and bool(_SEPARATOR.match(rows[index + 1])))
        units = _header_units(cells, is_header)
        if units or is_header:
            column_units, header_at = units, index
            continue
        for column in _inner_columns(cells, row):
            unit = column_units.get(column, caption_unit)
            numeric = _NUMERIC_CELL.match(cells[column]) if unit else None
            if numeric:
                cells[column] = f"{numeric.group(1)}{_to_won(numeric.group(2), unit)}{numeric.group(3)}"
                if column in column_units:
                    converted.setdefault(header_at, set()).add(column)
                else:
                    caption_used = True
    for index, columns in converted.items():
        for column in columns:
            table[index][column] = _HEADER_UNIT.sub(
                lambda m: f"{m.group(1)}원{m.group(3) or ''}{m.group(4)}", table[index][column]
            )
    return ["|".join(cells) for cells in table], caption_used
