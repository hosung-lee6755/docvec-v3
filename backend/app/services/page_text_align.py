"""미리보기 PDF 의 쪽 나눔에 맞춰 파싱된 본문을 쪽마다 자른다.

HWP·HWPX·DOCX 는 원본에 쪽 경계가 없거나(DOCX) 파서가 읽은 쪽과 미리보기 PDF 의 쪽이 다르다(HWP 는
LibreOffice 가 다시 배치한다). 원문 대조 탭은 미리보기 PDF 를 쪽 단위로 넘기므로, 파싱 본문도 같은 쪽으로
잘라야 두 화면이 함께 움직인다. 각 미리보기 쪽 첫머리 글을 본문에서 순서대로 찾아 쪽 경계로 삼는다.
"""

import re

# 쪽 첫머리에서 찾는 글자 수(글자·숫자만 센다). 짧으면 엉뚱한 곳에 맞고, 길면 조금만 달라도 못 찾는다
_ANCHOR_CHARS = 16
# 첫머리가 본문에 없을 때(머리말이 정제로 지워진 경우 등) 쪽 안에서 앞으로 밀어 가며 다시 찾는 간격과 한도
_ANCHOR_STEP = 8
_ANCHOR_SEARCH_CHARS = 400
_MIN_SHORT_PAGE_CHARS = 6
# 둘째 쪽부터 이 비율 이상 경계를 찾아야 맞춘 결과를 쓴다
_MIN_ANCHORED_SHARE = 0.5


def _normalize(text: str) -> tuple[str, list[int]]:
    """글자·숫자만 남긴 문자열과, 그 글자마다 원래 문자열에서의 위치를 돌려준다."""
    chars: list[str] = []
    positions: list[int] = []
    for index, char in enumerate(text):
        if char.isalnum():
            chars.append(char.lower())
            positions.append(index)
    return "".join(chars), positions


def _find_page_start(page_text: str, body: str, cursor: int) -> int | None:
    """쪽 첫머리 글이 본문(정규화)의 cursor 뒤에서 처음 나오는 자리. 못 찾으면 None."""
    page, _ = _normalize(page_text)
    if len(page) < _ANCHOR_CHARS:
        # 글이 적은 쪽은 쪽 글 전체로 찾는다. 너무 짧으면 엉뚱한 곳에 맞으므로 찾지 않는다
        found = body.find(page, cursor) if len(page) >= _MIN_SHORT_PAGE_CHARS else -1
        return found if found >= 0 else None
    last_offset = min(len(page) - _ANCHOR_CHARS, _ANCHOR_SEARCH_CHARS)
    # 쪽 번호("- 2 -")처럼 앞의 몇 글자만 본문에 없는 경우가 많아 처음 몇 자리는 한 글자씩 밀어 본다
    offsets = sorted(set(range(0, min(_ANCHOR_CHARS, last_offset + 1))) | set(range(0, last_offset + 1, _ANCHOR_STEP)))
    for offset in offsets:
        found = body.find(page[offset:offset + _ANCHOR_CHARS], cursor)
        if found >= 0:
            return found
    return None


# 파싱 본문이 표와 그림 앞에 붙이는 머리표 줄("[표 3]", "[그림 5]"). 미리보기 쪽에는 이 글이 없다
_LABEL_BEFORE_RE = re.compile(r"(?:^|\n)(\[(?:표|그림) \d+\])[ \t]*\n\s*$")


def _line_start(text: str, position: int, floor: int) -> int:
    """경계가 줄 가운데에 걸리면 그 줄 처음으로 당긴다(앞 경계보다 앞으로는 가지 않는다). 바로 앞 줄이 표·그림
    머리표뿐이면 머리표 줄 처음으로 당긴다. 미리보기 쪽은 표 칸 글로 시작하므로 그러지 않으면 머리표만 앞 쪽
    끝에 남는다(NS-AM 3쪽 끝의 "[표 4]", 2026-11-23)."""
    newline = text.rfind("\n", floor, position)
    start = newline + 1 if newline >= 0 else position
    label = _LABEL_BEFORE_RE.search(text[floor:start])
    return floor + label.start(1) if label else start


def split_text_by_pages(text: str, page_texts: list[str]) -> list[str] | None:
    """page_texts(미리보기 PDF 쪽마다의 글)에 맞춰 text 를 같은 수의 조각으로 자른다.

    경계를 찾지 못한 쪽은 빈 조각이 되고 그 내용은 앞 쪽에 남는다. 둘째 쪽부터 절반 넘게 못 찾으면 None 이다."""
    if not text or len(page_texts) < 2:
        return None
    body, positions = _normalize(text)
    starts: list[int | None] = [0]
    cursor = 0
    for page_text in page_texts[1:]:
        found = _find_page_start(page_text, body, cursor)
        if found is None:
            starts.append(None)
            continue
        starts.append(found)
        cursor = found + 1
    anchored = sum(1 for start in starts[1:] if start is not None)
    if anchored < (len(page_texts) - 1) * _MIN_ANCHORED_SHARE:
        return None

    offsets: list[int | None] = [0]
    previous = 0
    for start in starts[1:]:
        if start is None:
            offsets.append(None)
            continue
        offset = _line_start(text, positions[start], previous)
        offsets.append(offset)
        previous = offset

    pieces: list[str] = []
    for index, offset in enumerate(offsets):
        if offset is None:
            pieces.append("")
            continue
        end = next((o for o in offsets[index + 1:] if o is not None), len(text))
        pieces.append(text[offset:end])
    return pieces
