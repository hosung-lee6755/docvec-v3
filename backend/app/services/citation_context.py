"""인용 위치 보기(쪽 그림이 없는 형식): 인용한 청크가 문서 글의 어디인지 둘레 글과 함께 잘라 준다.

청크의 span_start/span_end는 정제·사전 적용·개인정보 마스킹을 거친 글(NORMALIZED 스냅샷) 기준이다.
호출하는 쪽이 그 글만 넘겨야 한다. 마스킹 전 원문(parsed_text)을 넘기면 인용이 가린 값이 드러난다.
"""
from typing import Any

CONTEXT_WINDOW_CHARS = 400
# 청크 본문의 앞부분만으로 찾을 때 쓰는 길이(너무 짧으면 엉뚱한 곳에 맞는다)
_MIN_PROBE_CHARS = 8


def _span_matches(text: str, chunk: Any) -> tuple[int, int] | None:
    start, end = chunk.span_start, chunk.span_end
    if start is None or end is None or not 0 <= start < end <= len(text):
        return None
    found = text[start:end]
    expected = chunk.original_text
    # 원문 구간을 적어 둔 청크는 같을 때만 믿는다. 적어 둔 것이 없으면 위치만 믿는다
    if expected is not None and found != expected and found != chunk.chunk_text:
        return None
    return start, end


def _search(text: str, chunk: Any) -> tuple[int, int] | None:
    for needle in (chunk.original_text, chunk.chunk_text):
        if not needle or not needle.strip():
            continue
        index = text.find(needle)
        if index >= 0:
            return index, index + len(needle)
    probe = (chunk.chunk_text or "").strip()[:_MIN_PROBE_CHARS * 5]
    if len(probe) >= _MIN_PROBE_CHARS:
        index = text.find(probe)
        if index >= 0:
            return index, index + len(probe)
    return None


def locate_chunk(text: str | None, chunk: Any) -> tuple[int, int] | None:
    """text 안에서 청크가 차지하는 (시작, 끝). 찾지 못하면 None."""
    if not text:
        return None
    return _span_matches(text, chunk) or _search(text, chunk)


def build_context(text: str | None, chunk: Any, window: int = CONTEXT_WINDOW_CHARS) -> dict[str, Any]:
    """인용 구간(text)과 앞뒤 window자. 위치를 못 찾으면 청크 본문만 돌려주고 둘레 글은 비운다."""
    span = locate_chunk(text, chunk)
    if span is None or text is None:
        return {
            "located": False, "before": "", "text": chunk.chunk_text or "", "after": "",
            "has_more_before": False, "has_more_after": False,
        }
    start, end = span
    before_start = max(0, start - window)
    after_end = min(len(text), end + window)
    return {
        "located": True,
        "before": text[before_start:start],
        "text": text[start:end],
        "after": text[end:after_end],
        "has_more_before": before_start > 0,
        "has_more_after": after_end < len(text),
    }
