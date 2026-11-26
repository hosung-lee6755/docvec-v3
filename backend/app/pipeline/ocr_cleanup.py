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
from collections import Counter

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


# Tesseract 줄 평균 신뢰도가 이보다 낮은 줄은 그림 글에서 뺀다. 전체 문서 그림 1,871줄을 다시 재 보니
# 40 미만 가운데 낱말·숫자 비율 기준을 통과한 264줄은 "wise waso22 45" 같은 잡음이 거의 전부였고,
# 40~50은 정상 줄과 섞여 있었다(2026-11-23)
MIN_FIGURE_LINE_CONFIDENCE = 40.0


def drop_low_confidence_lines(text: str, line_confidences: list[float]) -> str:
    """빈 줄이 아닌 줄과 신뢰도를 순서대로 맞대 기준 미만 줄을 뺀다. 줄 수가 다르면 맞댈 수 없으므로 그대로 둔다."""
    lines = (text or "").splitlines()
    if sum(1 for line in lines if line.strip()) != len(line_confidences):
        return text
    confidences = iter(line_confidences)
    kept = [line for line in lines if not line.strip() or next(confidences) >= MIN_FIGURE_LINE_CONFIDENCE]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()


def figure_text_for_body(text: str) -> str:
    """그림 인식 결과 가운데 본문에 넣을 만한 줄만 남긴다. 남는 게 너무 적으면 빈 문자열."""
    kept = [line for line in (text or "").splitlines() if _is_meaningful_line(line)]
    # 남은 줄의 글자 수가 아니라 뜻 있는 글자 수로 센다. 기호가 반인 ">|:    >| aevus"가 본문에 들어갔다(2026-11-25)
    if sum(_meaningful_chars(token) for line in kept for token in line.split()) < _MIN_BODY_CHARS:
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


# ---------------------------------------------------------------- 문서 어휘로 OCR 낱말 바로잡기
#
# 글자 층이 있는 PDF 에서도 쪽 제목을 그림 글자로 넣은 부분은 OCR 로 읽는다. EasyOCR 은 이런 제목을 "넥데이터 기반
# 심아버스 노선 수립올 위한 분석"처럼 한두 글자씩 틀리게 읽었다(심야버스 분석 요약본, 2026-11-25). 같은 문서의 글자 층에는
# 바른 낱말("빅데이터", "심야버스")이 여러 번 나오므로, 글자 층에 없는 낱말이 글자 층의 낱말과 한 글자만 다르면 그 낱말로
# 바꾼다. 잘못 바꾸지 않도록 세 글자 이상인 낱말만, 글자 층(띄어쓰기를 뺀 글)에 그대로 들어 있지 않은 낱말만, 한 글자만
# 다른 후보가 하나뿐이고 그 후보가 글자 층에 두 번 이상 나올 때만 바꾼다.
# 그림 OCR 의 "가속도", "지원내역"처럼 바른 낱말이 문서의 "휠속도", "지원내용"과 한 글자 차이인 경우도 있어서, 형태소 분석
# 점수(kiwi)가 후보보다 크게 나쁜 낱말만 바꾼다. 모든 PDF 에 시험 적용해 보니 바른 낱말은 점수 차이가 5.4 이하, 오인식은
# 대부분 9 이상이었다(2026-11-25).

_VOCAB_WORD_RE = re.compile(r"[가-힣]{3,}")
_MIN_SCORE_GAIN = 6.0
_kiwi = None


def _morph_score(word: str) -> float:
    """kiwi 형태소 분석의 가장 나은 점수. 높을수록 자연스러운 한국어다."""
    global _kiwi
    if _kiwi is None:
        from kiwipiepy import Kiwi

        _kiwi = Kiwi()
    return float(_kiwi.analyze(word)[0][1])
_MIN_VOCAB_OCCURRENCES = 2
# 낱말 끝에 붙는 조사와 흔한 끝 글자. 이 글자끼리 다른 것은 오인식이 아니라 다른 말이다
_PARTICLES = frozenset("을를이가은는의에도로와과만서고며")
# 목적격 조사 "을"을 "올", "울"로 읽은 경우. 뒤에 오는 말이 목적어를 받는 말일 때만 고친다
_OBJECT_PARTICLE_RE = re.compile(
    r"([가-힣]{2,})[올울](?=\s+(?:위한|위해|통한|통해|활용한|활용하여|대상으로|기반으로|중심으로|바탕으로"
    r"|주는|미치는|미칠|미친|받는|가진|갖는|수행|분석))"
)


class DocumentVocabulary:
    """한 문서 글자 층의 낱말. OCR 로 읽은 글의 한 글자 오인식을 이 낱말로 바로잡는다."""

    def __init__(self, native_text: str) -> None:
        self._joined = "".join((native_text or "").split())
        runs = _VOCAB_WORD_RE.findall(native_text or "")
        self._tokens = set(runs)
        # 낱말이 글자 층에 나온 횟수. 조사가 붙은 꼴("빅데이터를")도 세려고 낱말 앞부분마다 센다.
        # 큰 문서(수십만 자)에서 낱말마다 전체 글을 훑지 않도록 한 번에 센다
        occurrences: Counter = Counter()
        for run in runs:
            for end in range(3, len(run) + 1):
                occurrences[run[:end]] += 1
        self._by_shape: dict[tuple[int, int, str], set[str]] = {}
        for word in self._tokens:
            if occurrences[word] < _MIN_VOCAB_OCCURRENCES:
                continue
            # 끝 글자가 조사인 낱말은 끝 글자 자리로 짝짓지 않는다. "노선을"이 "노선도"를 바꿔 버린다
            last = len(word) - 1 if word[-1] in _PARTICLES else len(word)
            for index in range(last):
                key = (len(word), index, word[:index] + word[index + 1:])
                self._by_shape.setdefault(key, set()).add(word)

    def __bool__(self) -> bool:
        return bool(self._by_shape)

    def _fix_word(self, match: re.Match) -> str:
        word = match.group(0)
        if word in self._tokens:
            return word
        candidates: set[str] = set()
        last = len(word) - 1 if word[-1] in _PARTICLES else len(word)
        for index in range(last):
            candidates |= self._by_shape.get((len(word), index, word[:index] + word[index + 1:]), set())
        candidates.discard(word)
        # 띄어쓰기만 다른 글자 층 글("연료사용현황")에 그대로 있으면 오인식이 아니다. 비싼 확인이라 후보가 있을 때만 한다
        if len(candidates) != 1 or word in self._joined:
            return word
        candidate = candidates.pop()
        if _morph_score(candidate) - _morph_score(word) < _MIN_SCORE_GAIN:
            return word  # 바른 낱말일 수 있다("가속도" 와 "휠속도")
        return candidate

    def correct(self, text: str) -> str:
        if not text:
            return text
        fixed = _VOCAB_WORD_RE.sub(self._fix_word, text) if self._by_shape else text
        return _OBJECT_PARTICLE_RE.sub(r"\1을", fixed)


def correct_pages_with_vocabulary(pages: list, native_text: str) -> int:
    """쪽마다 글 조각과 표 칸을 문서 어휘로 바로잡는다. 바뀐 조각과 칸 수를 돌려준다."""
    vocabulary = DocumentVocabulary(native_text)
    changed = 0
    for page in pages:
        blocks = []
        for block in page.text_blocks:
            fixed = vocabulary.correct(block.text)
            if fixed != block.text:
                changed += 1
                block = dataclasses.replace(block, text=fixed)
            blocks.append(block)
        page.text_blocks = blocks
        tables = []
        for table in page.table_candidates:
            rows = [[vocabulary.correct(cell) for cell in row] for row in table.rows]
            changed += sum(a != b for old, new in zip(table.rows, rows) for a, b in zip(old, new))
            tables.append(table if rows == table.rows else dataclasses.replace(table, rows=rows))
        page.table_candidates = tables
    return changed
