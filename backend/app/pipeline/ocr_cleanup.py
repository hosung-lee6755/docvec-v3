"""OCR 결과에서 색인을 오염시키는 잡음을 거르고, 흔한 숫자 오인식을 되돌린다(2026-11-13 전처리 성능 검토).

- 그림 OCR: 그림 173개 가운데 74개는 비었고, 나머지 99개 가운데 35개는 의미 없는 글자였다. 줄마다 한글 단어,
  숫자, 영문 단어가 차지하는 비율을 보고 기준에 못 미치는 줄은 본문에서 뺀다. 남는 글자가 너무 적으면 그림
  텍스트 전체를 본문에 넣지 않는다(그림 자체와 인식 원문은 Document.images에 그대로 남는다).
- % 오인식: OCR이 `%`를 숫자 `9`나 `96`으로 읽어 87.00%가 87.009, 94.30%가 94.3096이 됐다. p값처럼 진짜
  소수 셋째 자리 숫자도 많으므로, 같은 표(또는 문단) 안에 비율을 뜻하는 말(환율·이율 제외)이 있고, 제대로
  찍힌 %가 하나도 없으며, 소수 셋째 자리 이상인 숫자가 둘 이상이고 모두 이 모양일 때만 고친다. 하나라도 다른
  끝자리가 섞이면 진짜 소수로 보고 두지 않는다. Docling 경로는 쪽 단위 OCR 여부를 알려주지 않아 텍스트
  레이어에서 읽은 표에도 적용되므로 조건을 좁게 잡았다.
"""
import dataclasses
import re

_MIN_BODY_CHARS = 10
_MIN_LINE_RATIO = 0.5
_ENGLISH_VOWEL_RATIO = (0.2, 0.6)

_HANGUL_WORD_RE = re.compile(r"[가-힣]{2,}")
_HANGUL_RE = re.compile(r"[가-힣]")
_NUMBER_TOKEN_RE = re.compile(r"[(\[]?\d[\d,.]*%?[)\]]?")
_ENGLISH_WORD_RE = re.compile(r"[A-Za-z]{4,}")
_PUNCT_EDGES = "()[]{}<>.,:;!?\"'“”‘’|-~*·"

_LONG_DECIMAL_RE = re.compile(r"(?<![\d.])\d+\.\d{3,}(?![\d.])")
_PERCENT_MISREAD_RE = re.compile(r"(\d{1,3}\.\d{2})(?:96|9)")
# 비율을 뜻하는 말. 환율·이율은 값이 원래 소수라 뺀다
_RATE_CONTEXT_RE = re.compile(r"(?<![환이])[율률]|치울|퍼센트")
# 같은 범위에 %가 제대로 찍힌 값이 있으면 OCR이 %를 읽을 수 있었다는 뜻이므로 고치지 않는다
_REAL_PERCENT_RE = re.compile(r"\d\s?%")
_MIN_SUSPECTS = 2
_MAX_PERCENT = 100.0


# ---------------------------------------------------------------- 그림 OCR


def _meaningful_chars(token: str) -> int:
    if _HANGUL_WORD_RE.search(token):
        return len(_HANGUL_RE.findall(token))
    if _NUMBER_TOKEN_RE.fullmatch(token) and sum(ch.isdigit() for ch in token) >= 2:
        return len(token)
    word = token.strip(_PUNCT_EDGES)
    if _ENGLISH_WORD_RE.fullmatch(word):
        vowels = sum(ch in "aeiouAEIOU" for ch in word) / len(word)
        low, high = _ENGLISH_VOWEL_RATIO
        if low <= vowels <= high:
            return len(word)
    return 0


def _is_meaningful_line(line: str) -> bool:
    tokens = line.split()
    total = sum(len(t) for t in tokens)
    if total == 0:
        return False
    return sum(_meaningful_chars(t) for t in tokens) >= total * _MIN_LINE_RATIO


def figure_text_for_body(text: str) -> str:
    """그림 인식 결과 가운데 본문에 넣을 만한 줄만 남긴다. 남는 게 너무 적으면 빈 문자열."""
    kept = [line for line in (text or "").splitlines() if _is_meaningful_line(line)]
    if sum(len("".join(line.split())) for line in kept) < _MIN_BODY_CHARS:
        return ""
    return "\n".join(kept)


# ---------------------------------------------------------------- % 오인식


def _suspect_value(number: str) -> str | None:
    match = _PERCENT_MISREAD_RE.fullmatch(number)
    if match is None or float(match.group(1)) > _MAX_PERCENT:
        return None
    return match.group(1) + "%"


def _corrections(scope: str) -> dict[str, str]:
    """scope(표 하나 또는 문단 하나) 안에서 고칠 숫자 → 고친 값. 조건이 안 맞으면 빈 dict."""
    if not _RATE_CONTEXT_RE.search(scope) or _REAL_PERCENT_RE.search(scope):
        return {}
    numbers = _LONG_DECIMAL_RE.findall(scope)
    fixes = {n: _suspect_value(n) for n in numbers}
    if len(numbers) < _MIN_SUSPECTS or any(v is None for v in fixes.values()):
        return {}
    return fixes


def _replace_numbers(text: str, fixes: dict[str, str]) -> str:
    return _LONG_DECIMAL_RE.sub(lambda m: fixes.get(m.group(0), m.group(0)), text)


def fix_percent_misreads(text: str) -> str:
    fixes = _corrections(text)
    return _replace_numbers(text, fixes) if fixes else text


def fix_percent_in_rows(rows: list[list[str]]) -> list[list[str]]:
    """표 행들을 하나의 범위로 보고 고친 새 행 목록을 돌려준다(원본은 그대로)."""
    fixes = _corrections("\n".join(" | ".join(cell or "" for cell in row) for row in rows))
    if not fixes:
        return [list(row) for row in rows]
    return [[_replace_numbers(cell, fixes) if cell else cell for cell in row] for row in rows]


def fix_percent_in_pages(pages: list) -> int:
    """추출된 쪽들의 문단·표 블록과 표 후보를 고친다. 고친 숫자 개수를 돌려준다."""
    count = 0
    for page in pages:
        new_blocks = []
        for block in page.text_blocks:
            fixed = fix_percent_misreads(block.text)
            if fixed != block.text:
                count += len(_LONG_DECIMAL_RE.findall(block.text)) - len(_LONG_DECIMAL_RE.findall(fixed))
                block = dataclasses.replace(block, text=fixed)
            new_blocks.append(block)
        page.text_blocks = new_blocks
        page.table_candidates = [_table_with_fixed_rows(table) for table in page.table_candidates]
    return count


def _table_with_fixed_rows(table):
    rows = fix_percent_in_rows(table.rows)
    return table if rows == table.rows else dataclasses.replace(table, rows=rows)
