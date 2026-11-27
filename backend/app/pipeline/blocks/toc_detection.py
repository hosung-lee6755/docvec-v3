"""목차 제목("목차", "차례", "CONTENTS")으로 목차 항목을 찾는다 (2026-11-17 구조 인식 점검).

HTML 보고서와 HWPX 문서의 목차에는 쪽 번호가 없어 "제목 ..... 3" 꼴만 보던 규칙이 놓쳤다. 놓친 항목은
번호 때문에 제목으로 분류되어 구조 트리에 같은 제목이 두 번 들어갔다(완료보고서는 제목 163개 중 106개).

목차 제목 바로 뒤의 짧은 줄을 항목 후보로 모으고, 본문이 첫 항목을 다시 쓰거나 긴 문단이 나오면 멈춘다.
후보의 절반 이상이 뒤의 본문에 다시 나와야 목차로 본다. 본문에 다시 나오지 않는 끝 쪽 후보는 뺀다.
줄 목록(정규식 경로)과 블록 목록(Docling 경로)에 똑같이 쓴다.
"""
import math
import re

TOC_TITLE_RE = re.compile(r"(목\s*차|차\s*례|contents)\s*[>:\]]?\s*$", re.IGNORECASE)
# 목차 제목 줄은 짧다. 문장 끝에 "목차"가 오는 경우를 거른다
TOC_TITLE_MAX_CHARS = 40
# 목차 제목은 문서 앞쪽에 있다. 이 개수의 줄(블록) 안에서만 찾는다
TOC_TITLE_SEARCH_LIMIT = 300
TOC_ENTRY_MAX_CHARS = 80
TOC_MAX_ENTRIES = 400
TOC_MIN_ENTRIES = 3
TOC_CONFIRM_RATIO = 0.5
# 항목 끝의 점선 리더와 쪽 번호. 본문 제목과 비교할 때 뗀다
_TOC_TAIL_RE = re.compile(r"(?:[\s.…·ㆍ‥_\-]{2,}|\s+)\d{1,4}\s*$")
_SPACE_RE = re.compile(r"\s+")


_TOC_TITLE_ONLY_RE = re.compile(r"[<\[(【]?\s*(목\s*차|차\s*례|contents|table\s+of\s+contents)\s*[>\])】:]?", re.IGNORECASE)


def is_toc_title(text: str) -> bool:
    """줄 전체가 목차 제목("목 차", "[차례]", "CONTENTS")인가. 문장 끝의 "목차"는 아니다."""
    return bool(_TOC_TITLE_ONLY_RE.fullmatch((text or "").strip()))


def toc_key(text: str) -> str:
    return _SPACE_RE.sub("", _TOC_TAIL_RE.sub("", text.strip()))


def _toc_title_index(texts: list[str]) -> int | None:
    for index, text in enumerate(texts[:TOC_TITLE_SEARCH_LIMIT]):
        stripped = text.strip()
        if stripped and len(stripped) <= TOC_TITLE_MAX_CHARS and TOC_TITLE_RE.search(stripped):
            return index
    return None


def _entry_candidates(texts: list[str], start: int) -> list[tuple[int, str]]:
    entries: list[tuple[int, str]] = []
    for index in range(start, len(texts)):
        stripped = texts[index].strip()
        if not stripped:
            continue
        if len(stripped) > TOC_ENTRY_MAX_CHARS or len(entries) >= TOC_MAX_ENTRIES:
            break
        key = toc_key(stripped)
        if entries and key == entries[0][1]:
            break  # 본문이 첫 항목으로 다시 시작한다
        entries.append((index, key))
    return entries


def titled_toc_indices(texts: list[str]) -> set[int]:
    """목차 항목인 줄(블록)의 위치. 목차가 없거나 확실하지 않으면 빈 집합."""
    title = _toc_title_index(texts)
    if title is None:
        return set()
    entries = _entry_candidates(texts, title + 1)
    if not entries:
        return set()
    later = {toc_key(t) for t in texts[entries[-1][0] + 1:] if t.strip()}
    confirmed = [index for index, key in entries if key and key in later]
    if len(confirmed) < max(TOC_MIN_ENTRIES, math.ceil(TOC_CONFIRM_RATIO * len(entries))):
        return set()
    last = confirmed[-1]
    return {index for index, _ in entries if index <= last}
