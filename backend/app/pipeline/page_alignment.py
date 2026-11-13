"""정제·치환·마스킹 전후 텍스트의 위치를 서로 옮긴다.

page_map과 구조 노드 위치는 text_extract가 만든 원문(parsed_text) 기준이다. chunk_split은 text_clean(공백 정리 등),
사전·동의어 치환, 개인정보 마스킹을 거친 텍스트를 자르므로 두 텍스트의 위치가 어긋난다. 길이 차이는 문서 뒤로
갈수록 쌓여, 988쪽 문서에서는 청크 쪽 번호가 중앙값 6쪽 어긋났다(2026-11-13 검토).

방법: 공백을 모두 뺀 두 문자열에서, 옮길 위치의 짧은 조각(앵커)을 상대 텍스트에서 찾는다. 위치 바로 뒤 조각을
먼저 찾고, 치환·마스킹된 곳에 걸리면 바로 앞 조각으로 찾은 뒤 그 끝을 쓴다. 그래도 안 되면 몇 칸씩 멀어지며
다시 찾는다. 같은 조각이 여러 번 나오면 길이 비율로 예상한 위치에 가장 가까운 것을 고른다. 끝내 못 찾으면
길이 비율로 추정한다.
"""
import bisect

from app.pipeline.tasks.process import _page_number_for_offset

_ANCHOR_CHARS = 12
_ANCHOR_TRIES = 8


def _squeeze(text: str) -> tuple[str, list[int]]:
    """공백을 모두 뺀 문자열과, 그 각 글자의 원래 위치."""
    chars: list[str] = []
    index: list[int] = []
    for i, ch in enumerate(text):
        if not ch.isspace():
            chars.append(ch)
            index.append(i)
    return "".join(chars), index


class OffsetMapper:
    """source 텍스트의 위치를 같은 내용을 가진 target 텍스트의 위치로 옮긴다."""

    def __init__(self, source: str, target: str) -> None:
        self._same = source == target
        self._target_len = len(target)
        if self._same:
            return
        self._ratio = len(target) / max(1, len(source))
        self._src_sq, self._src_idx = _squeeze(source)
        self._tgt_sq, self._tgt_idx = _squeeze(target)
        self._sq_ratio = len(self._tgt_sq) / max(1, len(self._src_sq))

    def map(self, offset: int) -> int:
        if self._same:
            return min(offset, self._target_len)
        start = bisect.bisect_left(self._src_idx, offset)
        if start >= len(self._src_sq):
            return self._target_len
        for attempt in range(_ANCHOR_TRIES):
            shift = attempt * _ANCHOR_CHARS
            found = self._after(start + shift, shift)
            if found is None:
                found = self._before(start - shift, shift)
            if found is not None:
                return self._target_pos(found)
        return min(self._target_len, int(offset * self._ratio))

    def _after(self, pos: int, shift: int) -> int | None:
        anchor = self._src_sq[pos:pos + _ANCHOR_CHARS]
        if len(anchor) < _ANCHOR_CHARS // 2:
            return None
        found = self._nearest(anchor, int(pos * self._sq_ratio))
        return None if found is None else max(0, found - shift)

    def _before(self, end: int, shift: int) -> int | None:
        end = max(0, end)
        begin = max(0, end - _ANCHOR_CHARS)
        anchor = self._src_sq[begin:end]
        if len(anchor) < _ANCHOR_CHARS // 2:
            return None
        found = self._nearest(anchor, int(begin * self._sq_ratio))
        return None if found is None else found + len(anchor) + shift

    def _target_pos(self, sq_pos: int) -> int:
        if sq_pos >= len(self._tgt_idx):
            return self._target_len
        return self._tgt_idx[sq_pos]

    def _nearest(self, anchor: str, expected: int) -> int | None:
        after = self._tgt_sq.find(anchor, max(0, expected))
        before = self._tgt_sq.rfind(anchor, 0, max(0, expected) + len(anchor))
        candidates = [p for p in (after, before) if p >= 0]
        if not candidates:
            return None
        return min(candidates, key=lambda p: abs(p - expected))


class PageLocator:
    """정규화된 텍스트(청크 기준)의 위치가 원문 page_map의 몇 쪽인지 찾는다."""

    def __init__(self, parsed_text: str, page_map: list[list[int]] | None, normalized_text: str) -> None:
        self._page_map = page_map
        self._mapper = OffsetMapper(normalized_text, parsed_text) if page_map else None

    def page_for(self, offset: int) -> int | None:
        if not self._page_map or self._mapper is None:
            return None
        return _page_number_for_offset(self._page_map, self._mapper.map(offset))
