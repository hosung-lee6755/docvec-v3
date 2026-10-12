"""추출 텍스트가 검색에 쓸 수 있는지를 가늠하는 순수 함수 모음(quality_check 가 사용).

표 문법(`|`, `---`)·제목 기호·공백만 남은 결과는 길이로는 "추출됨"처럼 보이지만 검색할 내용이 없다.
OCR 이 글자 사이를 벌려 놓은 결과(한 글자 토큰 다수)는 단어 단위 검색·임베딩이 모두 무력해진다.
"""
import re

_NON_CONTENT_RE = re.compile(r"[\s|\-#*>_`~:.]+")
_SINGLE_HANGUL_TOKEN_RE = re.compile(r"[가-힣]")


def usable_char_count(text: str) -> int:
    """마크다운 표/제목 기호와 공백을 뺀 실질 글자 수."""
    return len(_NON_CONTENT_RE.sub("", text or ""))


def single_char_token_ratio(text: str) -> float:
    """공백 기준 토큰 중 한글 한 글자짜리 비율 — OCR 글자 벌어짐 지표(정상 문서 ~5%, 실패한 OCR ~40%)."""
    tokens = (text or "").split()
    if not tokens:
        return 0.0
    return sum(1 for t in tokens if _SINGLE_HANGUL_TOKEN_RE.fullmatch(t)) / len(tokens)
