"""원문 대조 탭의 쪽 경계를 경계마다 다시 고른다.

split_text_for_preview 는 쪽 나누는 방식 몇 가지 가운데 문서 전체로 미리보기 글과 가장 잘 맞는 하나를 고른다. 그런데
방식마다 잘 맞는 경계가 달라, 고른 방식이 틀린 경계에서는 다음 쪽 첫 문단이 앞 쪽 끝에 붙거나 문단 가운데에서
잘렸다(컨설팅 HWP 30쪽, 예측분석 설명서 75쪽, 2026-11-27). 여기서는 경계마다 모든 방식이 내놓은 위치와 그 둘레의
문단 경계를 후보로 두고, 경계 앞뒤 두 쪽이 각자의 미리보기 글과 가장 많이 맞는 위치를 고른다.
"""
from bisect import bisect_left, bisect_right

import re

from app.services.page_text_align import _FIT_SHINGLE as _SHINGLE
from app.services.page_text_align import _normalize, _shingles

# 후보 위치 둘레에서 더 살펴볼 문단 경계 수(앞뒤 각각)
_NEAR_BORDERS = 3
# 경계를 옮기려면 점수가 이만큼 올라야 한다(글 조각 수)
_MIN_GAIN = 4
_PASSES = 3
# 덧셈 점수가 평평할 때 재현율로 경계를 옮기려면 두 쪽 재현율 합이 이만큼 올라야 한다
_MIN_RECALL_GAIN = 0.02
_BORDER_RE = re.compile(r"\n\n+")
# 표 구분선(|---|---|) 줄. 그 앞에서 자르면 머리 행과 구분선이 갈라진다
_DIVIDER_RE = re.compile(r"\|?\s*:?-{3,}")


def _cuts(pieces: list[str]) -> list[int]:
    """조각 사이 경계의 본문 위치."""
    cuts, position = [], 0
    for piece in pieces[:-1]:
        position += len(piece)
        cuts.append(position)
    return cuts


def _options(index: int, candidate_cuts: list[list[int]], borders: list[int], low: int, high: int) -> list[int]:
    """경계 index 의 후보 위치. 방식마다 내놓은 위치와 그 사이·둘레의 문단 경계 가운데 앞뒤 경계 안에 드는 것."""
    positions = {min(max(cuts[index], low), high) for cuts in candidate_cuts}
    first = bisect_left(borders, min(positions))
    last = bisect_right(borders, max(positions))
    near = borders[max(0, first - _NEAR_BORDERS):last + _NEAR_BORDERS]
    return sorted(position for position in positions.union(near) if low <= position <= high)


def _word_options(text: str, cut: int, low: int, high: int) -> list[int]:
    """cut 바로 앞뒤 덩어리(빈 줄로 나뉜 문단이나 표 하나) 안의 낱말·줄 첫머리 위치.

    원본은 문단이나 표 행 가운데에서도 쪽이 바뀐다. 문단 경계에서만 자르면 쪽을 넘어가는 문단 전체가 한 쪽에 들어가
    뒤 쪽 글이 앞 쪽에 보였다(2026-11-27). 행 가운데에서 잘린 표 조각은 화면(closeSplitTables)이 닫고 다시 연다."""
    start = text.rfind("\n\n", low, max(low, cut - 1))
    start = low if start < 0 else start + 2
    end = text.find("\n\n", min(cut + 1, high), high)
    end = high if end < 0 else end
    return [
        position for position in range(start + 1, end)
        if text[position - 1] in " \n" and not text[position].isspace() and not _DIVIDER_RE.match(text, position)
    ]


def _natural(text: str, position: int) -> int:
    """점수가 같은 위치 가운데 고를 차례. 문단 경계, 줄 첫머리, 낱말 첫머리 순이다(두 쪽에 다 있는 "2005~2023" 같은
    글 앞뒤는 점수가 같아, 행 가운데보다 행 경계에서 자른다)."""
    if text.startswith("\n\n", position - 2):
        return 2
    return 1 if text[position - 1:position] == "\n" else 0


def _cut_scores(text: str, options: list[int], low: int, high: int, before: set[str], after: set[str]) -> dict[int, int]:
    """후보 위치마다, 경계 앞 글 조각은 앞 쪽 미리보기 글에 있으면 +1·뒤 쪽 글에 있으면 -1, 경계 뒤 글 조각은 그 반대로
    더한 값(앞뒤 공통 부분을 뺀 상대 점수). 두 쪽 모두에 있거나 어디에도 없는 글은 0 이라 경계를 움직이지 않는다.

    글 조각마다 따로 세므로, 처음에 쓴 "맞는 서로 다른 조각 수"와 달리 두 쪽에 다 나오는 글(그림 안 글, 각주 제목)을
    옮겨 한쪽이 새 조각을 얻는 일로 경계가 끌려가지 않는다."""
    normalized, positions = _normalize(text[low:high])
    in_before = [False] * len(normalized)
    in_after = [False] * len(normalized)
    for start in range(max(0, len(normalized) - _SHINGLE + 1)):
        gram = normalized[start:start + _SHINGLE]
        for marks, page in ((in_before, before), (in_after, after)):
            if gram in page:
                marks[start:start + _SHINGLE] = [True] * _SHINGLE
    # 글자마다 그 글자를 덮는 조각이 어느 쪽 글에 있는지로 센다. 쪽 끝 세 글자("어느 하나에")처럼 온전한 조각이 그
    # 글자에서 시작하지 않아도 앞 조각이 덮으므로, 조각 시작 위치로 셀 때처럼 경계가 한 낱말 앞에서 멈추지 않는다
    gains = [0]
    for here, there in zip(in_before, in_after):
        gains.append(gains[-1] + here - there)
    return {position: gains[bisect_left(positions, position - low)] for position in options}


def _recalls(text: str, options: list[int], low: int, high: int, before: set[str], after: set[str]) -> dict[int, float]:
    """후보 위치마다 앞뒤 두 쪽이 각자 미리보기 글 조각을 얼마나 담는지(재현율)의 합. 위치를 차례로 넓히며 누적해 센다."""
    normalized, positions = _normalize(text[low:high])
    grams = [normalized[start:start + _SHINGLE] for start in range(max(0, len(normalized) - _SHINGLE + 1))]
    ends = {position: bisect_left(positions, position - low) for position in options}
    left: dict[int, int] = {}
    seen: set[str] = set()
    start = 0
    for position in options:
        while start < len(grams) and start + _SHINGLE <= ends[position]:
            if grams[start] in before:
                seen.add(grams[start])
            start += 1
        left[position] = len(seen)
    right: dict[int, int] = {}
    seen = set()
    start = len(grams) - 1
    for position in reversed(options):
        while start >= 0 and start >= ends[position]:
            if grams[start] in after:
                seen.add(grams[start])
            start -= 1
        right[position] = len(seen)
    return {p: left[p] / max(len(before), 1) + right[p] / max(len(after), 1) for p in options}


def _choose(text: str, options: list[int], current: int, scores: dict[int, int], recalls: dict[int, float]) -> int:
    """옮길 경계 위치. 옮길 곳이 없으면 current.

    덧셈 점수가 뚜렷이 오르고 재현율 합이 떨어지지 않는 위치를 먼저 고른다(덧셈 점수만 보면 표 행처럼 두 쪽에 비슷한
    글이 되풀이되는 곳에서 경계가 끌려가 한 쪽이 비었다, 물동량 영향요인 129쪽). 그런 곳이 없으면 덧셈 점수가 떨어지지
    않으면서 재현율 합이 뚜렷이 오르는 위치를 고른다(지역 이름만 다른 행이 이어지는 표는 덧셈 점수가 거의 평평하다,
    같은 문서 126쪽)."""
    score, recall = scores[current], recalls[current]
    by_score = [p for p in options if scores[p] >= score + _MIN_GAIN and recalls[p] >= recall]
    if by_score:
        return max(by_score, key=lambda p: (scores[p], recalls[p], _natural(text, p)))
    by_recall = [p for p in options if scores[p] >= score and recalls[p] >= recall + _MIN_RECALL_GAIN]
    if by_recall:
        return max(by_recall, key=lambda p: (recalls[p], scores[p], _natural(text, p)))
    return current


def refine_boundaries(pieces: list[str], candidates: list[list[str]], page_texts: list[str]) -> list[str]:
    """pieces 의 쪽 경계를 경계마다 다시 고른 새 조각 목록. 조각을 이으면 본문 그대로다.

    candidates 는 같은 본문을 다른 방식으로 나눈 조각 목록들이다. 본문을 그대로 다시 만들지 못하는 후보는 쓰지 않는다."""
    text = "".join(pieces)
    if len(pieces) < 2 or len(pieces) != len(page_texts):
        return pieces
    cuts = _cuts(pieces)
    candidate_cuts = [_cuts(c) for c in candidates if len(c) == len(pieces) and "".join(c) == text] + [list(cuts)]
    expected = [_shingles(page_text) for page_text in page_texts]
    borders = [match.end() for match in _BORDER_RE.finditer(text)]
    for _ in range(_PASSES):
        changed = False
        for index, current in enumerate(cuts):
            low = cuts[index - 1] if index else 0
            high = cuts[index + 1] if index + 1 < len(cuts) else len(text)
            options = sorted({
                current, *_options(index, candidate_cuts, borders, low, high), *_word_options(text, current, low, high),
            })
            before, after = expected[index], expected[index + 1]
            scores = _cut_scores(text, options, low, high, before, after)
            chosen = _choose(text, options, current, scores, _recalls(text, options, low, high, before, after))
            if chosen != current:
                cuts[index] = chosen
                changed = True
        if not changed:
            break
    bounds = [0, *cuts, len(text)]
    return [text[start:end] for start, end in zip(bounds, bounds[1:])]
