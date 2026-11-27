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
# 찾은 첫머리 뒤로 이만큼(글자·숫자)이 이어서 맞아야 그 자리를 쪽 시작으로 믿는다
_VERIFY_CHARS = 32
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
    # 쪽 번호("- 2 -")처럼 앞의 몇 글자만 본문에 없는 경우가 많아 처음 몇 자리는 한 글자씩 밀어 본다
    offsets = _anchor_offsets(page)
    # 첫머리 뒤의 글까지 이어서 맞는 자리를 먼저 찾는다. 첫머리("Risk Scoring Engine")가 앞 쪽 본문 문장에도 나오면
    # 그 문장에서 쪽이 시작했다(AIDE 구축제안서 3쪽, 2026-11-25). 이어지는 글이 다른 자리뿐이면 예전처럼 첫 자리를 쓴다
    first_found: int | None = None
    for offset in offsets:
        anchor = page[offset:offset + _ANCHOR_CHARS]
        longer = page[offset:offset + _VERIFY_CHARS]
        found = body.find(anchor, cursor)
        if found >= 0 and first_found is None:
            first_found = found
        while found >= 0:
            if len(longer) <= len(anchor) or body.startswith(longer, found):
                return found
            found = body.find(anchor, found + 1)
    return first_found


# 파싱 본문이 표와 그림 앞에 붙이는 머리표 줄("[표 3]", "[그림 5]"). 미리보기 쪽에는 이 글이 없다
_LABEL_BEFORE_RE = re.compile(r"(?:^|\n)(\[(?:표|그림) \d+\])[ \t]*\n\s*$")


# 쪽 경계를 줄 처음으로 당기는 최대 글자 수. 더 멀면 문단이나 표 행 가운데에서 쪽이 넘어간 것이다.
# 표 행도 같다. 예전에는 표 행을 400자까지 행 처음으로 당겨, 원본에서 쪽을 넘어가는 칸 글이 통째로 다음 쪽에
# 붙거나(고도화보고서 HTML 60쪽) 한 칸짜리 글상자의 앞 쪽이 비었다(조사료 사업시행지침 HWPX 26쪽, 2026-11-26).
# 쪽마다 나뉜 표 조각은 원문 대조 화면이 표로 이어 그린다(frontend pageTableFragments)
_MAX_LINE_PULL_CHARS = 60
# 표 행을 자를 자리. 칸 안 줄바꿈(" / ")이나 칸 경계(" | ")를 띄어쓰기보다 먼저 쓴다
_ROW_BREAKS = (" / ", " | ")


def _break_inside(text: str, start: int, position: int, is_table_row: bool) -> int:
    """줄 가운데 position 바로 앞의 끊을 자리. 표 행이면 칸 안 줄바꿈이나 칸 경계를 먼저 찾는다."""
    if is_table_row:
        # 쪽이 넘어간 자리 가까이의 칸 안 줄바꿈·칸 경계만 쓴다. 먼 칸 경계까지 당기면 앞 쪽 칸 글이 다음 쪽으로
        # 넘어간다(고도화보고서 HTML 97쪽, 2026-11-26)
        near = max(start, position - _MAX_LINE_PULL_CHARS)
        cuts = [text.rfind(mark, near, position) + len(mark) for mark in _ROW_BREAKS if text.rfind(mark, near, position) > start]
        if cuts:
            return max(cuts)
    space = max(text.rfind(" ", start, position), text.rfind("\t", start, position))
    return space + 1 if space >= start else position


def _line_start(text: str, position: int, floor: int) -> int:
    """경계가 줄 가운데에 걸리면 그 줄 처음으로 당긴다(앞 경계보다 앞으로는 가지 않는다). 바로 앞 줄이 표·그림
    머리표뿐이면 머리표 줄 처음으로 당긴다. 미리보기 쪽은 표 칸 글로 시작하므로 그러지 않으면 머리표만 앞 쪽
    끝에 남는다(NS-AM 3쪽 끝의 "[표 4]", 2026-11-23).

    HWP 문단은 본문에서 한 줄이라 여러 줄짜리 문단이 쪽 경계에 걸치면 문단 전체가 앞 쪽에 붙어, 원본과 쪽 내용이
    달라 보였다(분석결과보고서 HWP, 2026-11-26). 줄 처음이 멀면 그 자리 바로 앞 띄어쓰기에서 자른다. 표 행은
    가까운 칸 안 줄바꿈이나 칸 경계에서 자른다."""
    newline = text.rfind("\n", floor, position)
    start = newline + 1 if newline >= 0 else position
    if position - start > _MAX_LINE_PULL_CHARS:
        return _break_inside(text, start, position, text.startswith("|", start))
    label = _LABEL_BEFORE_RE.search(text[floor:start])
    return floor + label.start(1) if label else start


# 쪽 대부분에 되풀이되는 줄(머리말, 꼬리말, "Page 3")은 쪽 첫머리로 쓰지 않는다. 이만큼의 쪽에 나오면 되풀이 줄이다
_RUNNING_LINE_SHARE = 0.5
_RUNNING_LINE_MIN_PAGES = 3
_DIGITS_RE = re.compile(r"\d+")


# 글자 없이 숫자만 있는 줄 가운데 되풀이 줄로 볼 수 있는 것은 쪽 번호 모양("3", "- 3 -", "(3)", "3 / 10")뿐이다
_PAGE_NUMBER_KEY_RE = re.compile(r"^[-–—(\[\s]*#(?:\s*/\s*#)?[-–—)\]\s]*$")


def _line_key(line: str) -> str:
    return _DIGITS_RE.sub("#", " ".join(line.split()))


def _may_run(key: str) -> bool:
    """되풀이 줄(머리말·꼬리말·쪽 번호)이 될 수 있는 줄인지. 숫자를 "#" 로 바꾸면 표의 숫자 칸("13,229", "360,196")이
    모두 "#,#" 로 같아져 쪽마다 되풀이되는 줄로 지워졌다. 여러 쪽에 걸친 숫자 표 쪽은 남는 글이 거의 없어 쪽 첫머리를
    못 찾았고, 그 쪽이 비고 표가 앞 쪽에 몰렸다(예측분석 설계보고서 HWP 12·13쪽, 2026-11-26). 글자가 있는 줄과 쪽 번호
    모양만 되풀이 줄로 본다."""
    return any(char.isalpha() for char in key) or bool(_PAGE_NUMBER_KEY_RE.match(key))


def _without_running_lines(page_texts: list[str]) -> list[str]:
    """쪽마다 되풀이되는 줄을 뺀 쪽 글. 숫자만 다른 줄("Page 2", "Page 3")도 같은 줄로 본다.

    AIDE 검수기준서 DOCX(2026-11-25)는 미리보기 쪽마다 "AIDE | Driver DNA™ Prototype / 검수기준서 / Page N" 머리말이
    있는데 본문에는 없다. 이 머리말로 첫머리를 찾다가 본문의 비슷한 글에 맞아 2~7쪽이 비고 8쪽에 모든 글이 몰렸다."""
    if len(page_texts) < _RUNNING_LINE_MIN_PAGES:
        return page_texts
    counts: dict[str, int] = {}
    for page_text in page_texts:
        for key in {_line_key(line) for line in page_text.splitlines() if line.strip()}:
            counts[key] = counts.get(key, 0) + 1
    running = {
        key for key, count in counts.items() if count >= len(page_texts) * _RUNNING_LINE_SHARE and _may_run(key)
    }
    if not running:
        return page_texts
    return ["\n".join(line for line in page_text.splitlines() if _line_key(line) not in running) for page_text in page_texts]


def split_text_by_pages(text: str, page_texts: list[str]) -> list[str] | None:
    """page_texts(미리보기 PDF 쪽마다의 글)에 맞춰 text 를 같은 수의 조각으로 자른다.

    경계를 찾지 못한 쪽은 빈 조각이 되고 그 내용은 앞 쪽에 남는다. 둘째 쪽부터 절반 넘게 못 찾으면 None 이다."""
    if not text or len(page_texts) < 2:
        return None
    body, positions = _normalize(text)
    starts: list[int | None] = [0]
    cursor = 0
    for page_text in _without_running_lines(page_texts)[1:]:
        found = _find_page_start(page_text, body, cursor)
        if found is None:
            starts.append(None)
            continue
        starts.append(found)
        cursor = found + 1
    return _pieces_from_starts(text, positions, starts)


def _pieces_from_starts(text: str, positions: list[int], starts: list[int | None]) -> list[str] | None:
    """쪽마다 찾은 시작 자리(정규화 본문 위치, 못 찾은 쪽은 None)로 text 를 자른다. 절반 넘게 못 찾았으면 None."""
    anchored = sum(1 for start in starts[1:] if start is not None)
    if anchored < (len(starts) - 1) * _MIN_ANCHORED_SHARE:
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


# 맞춤 나누기: 쪽마다 볼 시작 후보 수(첫머리 하나당, 쪽 전체), 쪽 시작으로 받아들일 최소 맞음 정도
_CANDIDATES_PER_ANCHOR = 30
_MAX_CANDIDATES = 80
_MIN_START_SCORE = 0.3


def _anchor_offsets(page: str) -> list[int]:
    last_offset = min(len(page) - _ANCHOR_CHARS, _ANCHOR_SEARCH_CHARS)
    return sorted(set(range(0, min(_ANCHOR_CHARS, last_offset + 1))) | set(range(0, last_offset + 1, _ANCHOR_STEP)))


def _occurrences(needle: str, body: str, limit: int) -> list[int]:
    found, out = body.find(needle), []
    while found >= 0 and len(out) < limit:
        out.append(found)
        found = body.find(needle, found + 1)
    return out


def _candidate_starts(page: str, body: str) -> list[int]:
    """정규화한 쪽 글의 첫머리가 본문 어디에 나오든 모두(본문 처음부터). 짧은 쪽은 쪽 글 전체로 찾는다."""
    if len(page) < _ANCHOR_CHARS:
        return _occurrences(page, body, _MAX_CANDIDATES) if len(page) >= _MIN_SHORT_PAGE_CHARS else []
    seen: dict[int, None] = {}
    for offset in _anchor_offsets(page):
        for found in _occurrences(page[offset:offset + _ANCHOR_CHARS], body, _CANDIDATES_PER_ANCHOR):
            seen.setdefault(found)
            if len(seen) >= _MAX_CANDIDATES:
                return list(seen)
    return list(seen)


def _best_increasing(nodes: list[tuple[int, int, float]]) -> list[tuple[int, int]]:
    """(쪽 번호, 시작 자리, 맞음 정도) 가운데 쪽 번호와 시작 자리가 함께 커지는 묶음 중 맞음 정도 합이 가장 큰 것.
    쪽마다 많아야 하나를 고른다. 시작 자리 순위로 최댓값 펜윅 나무를 써서 n log n 에 푼다."""
    keys = sorted({start for _page, start, _score in nodes})
    rank = {start: i + 1 for i, start in enumerate(keys)}
    tree: list[tuple[float, int]] = [(0.0, -1)] * (len(keys) + 1)

    def query(i: int) -> tuple[float, int]:
        best = (0.0, -1)
        while i > 0:
            best = max(best, tree[i])
            i -= i & -i
        return best

    def update(i: int, value: tuple[float, int]) -> None:
        while i <= len(keys):
            tree[i] = max(tree[i], value)
            i += i & -i

    totals: list[float] = []
    previous: list[int] = []
    index = 0
    while index < len(nodes):
        group_end = index
        while group_end < len(nodes) and nodes[group_end][0] == nodes[index][0]:
            group_end += 1
        # 같은 쪽 후보끼리 잇지 않도록 한 쪽 후보를 모두 잰 뒤에 나무에 넣는다
        for node in range(index, group_end):
            total, before = query(rank[nodes[node][1]] - 1)
            totals.append(total + nodes[node][2])
            previous.append(before)
        for node in range(index, group_end):
            update(rank[nodes[node][1]], (totals[node], node))
        index = group_end
    if not totals:
        return []
    node = max(range(len(totals)), key=lambda n: (totals[n], -n))
    chosen: list[tuple[int, int]] = []
    while node >= 0:
        chosen.append((nodes[node][0], nodes[node][1]))
        node = previous[node]
    return chosen[::-1]


def split_text_by_alignment(text: str, page_texts: list[str]) -> list[str] | None:
    """쪽마다 첫머리가 나오는 모든 자리를 후보로 두고, 뒤 글이 그 쪽 글과 맞는 정도의 합이 가장 큰 순서대로 고른다.

    첫머리 찾기(split_text_by_pages)는 앞에서부터 처음 맞는 자리를 쓴다. 같은 표가 품목마다 되풀이되는 보고서는
    쪽 첫머리가 앞 쪽 표에 먼저 맞아(뒤 32자도 같았다) 한 번 어긋나면 뒤 쪽이 모두 비었다(물동량 영향요인 분석
    HWP 169쪽 가운데 72쪽, 2026-11-25). 쪽마다 따로 맞음 정도를 재고 전체 순서로 고르면 한 쪽의 오인이 뒤로 번지지 않는다."""
    if not text or len(page_texts) < 2:
        return None
    body, positions = _normalize(text)
    pages = [_normalize(page)[0] for page in _without_running_lines(page_texts)]
    nodes: list[tuple[int, int, float]] = []
    for number, page in enumerate(pages[1:], start=1):
        expected = _grams(page)
        if not expected:
            continue
        for start in _candidate_starts(page, body):
            score = len(expected & _grams(body[start:start + len(page)])) / len(expected)
            if start > 0 and score >= _MIN_START_SCORE:
                nodes.append((number, start, score))
    starts: list[int | None] = [0] + [None] * (len(pages) - 1)
    for number, start in _best_increasing(nodes):
        starts[number] = start
    return _pieces_from_starts(text, positions, starts)


# 전체 맞춤: 양쪽 글에 한 번씩만 나오는 이 길이의 글자 조각을 기준점으로 쓴다
_GLOBAL_ANCHOR_CHARS = 12


def _unique_grams(text: str) -> dict[str, int]:
    """한 번만 나오는 글자 조각 → 그 자리."""
    places: dict[str, int] = {}
    for index in range(len(text) - _GLOBAL_ANCHOR_CHARS + 1):
        gram = text[index:index + _GLOBAL_ANCHOR_CHARS]
        places[gram] = -1 if gram in places else index
    return {gram: index for gram, index in places.items() if index >= 0}


def _ordered_anchors(preview: str, body: str) -> list[tuple[int, int]]:
    """양쪽에 한 번씩만 나오는 조각의 (미리보기 자리, 본문 자리) 가운데 두 자리가 함께 커지는 가장 긴 묶음."""
    in_body = _unique_grams(body)
    pairs = sorted((p, in_body[g]) for g, p in _unique_grams(preview).items() if g in in_body)
    tails: list[int] = []  # 길이 k+1 인 증가 묶음의 마지막 본문 자리가 가장 작은 쌍의 번호
    previous: list[int] = []
    for index, (_p, b) in enumerate(pairs):
        lo, hi = 0, len(tails)
        while lo < hi:
            mid = (lo + hi) // 2
            if pairs[tails[mid]][1] < b:
                lo = mid + 1
            else:
                hi = mid
        previous.append(tails[lo - 1] if lo else -1)
        if lo == len(tails):
            tails.append(index)
        else:
            tails[lo] = index
    chain: list[tuple[int, int]] = []
    node = tails[-1] if tails else -1
    while node >= 0:
        chain.append(pairs[node])
        node = previous[node]
    return chain[::-1]


def split_text_by_global_alignment(text: str, page_texts: list[str]) -> list[str] | None:
    """미리보기 전체 글과 본문 전체 글을 맞춰 쪽 경계를 본문으로 옮긴다.

    쪽 첫머리 찾기는 쪽 첫 16자만 본다. 미리보기가 줄을 다시 배치해 문단이 쪽 경계에 걸치면 앞 쪽 끝 문단부터 쪽을
    시작하거나 다음 쪽 첫 문단까지 끌어왔다(예측분석 설계보고서 HWP, 2026-11-26). 양쪽에 한 번씩만 나오는 글 조각을
    순서대로 이어 맞춘 뒤, 쪽마다 그 쪽 안의 첫 기준점에서 쪽 시작까지의 거리만큼 본문에서 되돌아간다. 앞 쪽의 마지막
    기준점 뒤로는 넘어가지 않는다(머리말처럼 본문에 없는 글이 쪽 앞에 있어도 앞 쪽 글을 가져오지 않게)."""
    if not text or len(page_texts) < 2:
        return None
    body, positions = _normalize(text)
    pages = [_normalize(page)[0] for page in page_texts]
    page_starts: list[int] = []
    total = 0
    for page in pages:
        page_starts.append(total)
        total += len(page)
    anchors = _ordered_anchors("".join(pages), body)
    starts: list[int | None] = [0] + [None] * (len(pages) - 1)
    cursor = 0
    floor = 0  # 앞 쪽 마지막 기준점이 끝나는 본문 자리
    last_pair: tuple[int, int] | None = None  # 지금까지 본 마지막 기준점(미리보기 자리, 본문 자리)
    for number in range(len(pages)):
        page_end = page_starts[number] + len(pages[number])
        while cursor < len(anchors) and anchors[cursor][0] < page_starts[number]:
            cursor += 1
        inside = [pair for pair in anchors[cursor:] if pair[0] < page_end][:1]
        if number and inside:
            p, b = inside[0]
            starts[number] = max(b - (p - page_starts[number]), floor)
        elif number and last_pair is not None:
            # 쪽 안의 글이 모두 다른 쪽에도 있어 기준점이 없다(되풀이되는 표). 앞 기준점에서 미리보기로 떨어진 만큼
            # 본문에서도 떨어진 자리를 쪽 시작으로 본다. 그러지 않으면 이 쪽이 비고 내용이 앞 쪽에 붙는다
            p, b = last_pair
            starts[number] = min(max(b + (page_starts[number] - p), floor), len(body) - 1)
        last = cursor
        while last < len(anchors) and anchors[last][0] < page_end:
            last += 1
        if last > cursor:
            last_pair = anchors[last - 1]
            floor = last_pair[1] + _GLOBAL_ANCHOR_CHARS
    return _pieces_from_starts(text, positions, _increasing(starts))


def _increasing(starts: list[int | None]) -> list[int | None]:
    """앞 쪽 시작보다 앞서는 추정 시작은 버린다(None). 쪽 조각이 거꾸로 잘리지 않게 한다."""
    kept: list[int | None] = []
    previous = -1
    for start in starts:
        if start is not None and start <= previous:
            kept.append(None)
            continue
        kept.append(start)
        if start is not None:
            previous = start
    return kept


# 쪽 조각이 미리보기 쪽 글과 맞는 정도를 잴 때 쓰는 글자 조각 길이와, 잴 만큼 글이 있는 쪽의 최소 조각 수
_FIT_SHINGLE = 4
_FIT_MIN_SHINGLES = 30


def pages_from_page_map(text: str, page_map: list | None, page_count: int) -> list[str] | None:
    """처리 때 저장한 page_map([끝 위치, 쪽 번호] 목록)으로 text 를 page_count 쪽으로 나눈다.

    HWP·HWPX 는 텍스트 추출이 미리보기 PDF 로 블록마다 쪽을 맞춰 page_map 을 남긴다. 미리보기 쪽 수를 넘는 쪽
    번호는 마지막 쪽에 붙인다. 쪽이 하나뿐이면 쪽 정보가 없는 것이므로 None 이다."""
    if not text or not page_map or len(page_map) < 2 or page_count < 1:
        return None
    pieces = [""] * page_count
    start = 0
    for end, page_number in page_map:
        index = min(max(int(page_number), 1), page_count) - 1
        pieces[index] += text[start:end]
        start = end
    if start < len(text):
        pieces[-1] += text[start:]
    return pieces


def _grams(normalized: str) -> set[str]:
    return {normalized[i:i + _FIT_SHINGLE] for i in range(max(0, len(normalized) - _FIT_SHINGLE + 1))}


def _shingles(text: str) -> set[str]:
    return _grams(_normalize(text)[0])


def _page_fit(pieces: list[str], page_texts: list[str]) -> float:
    """쪽마다 미리보기 글 조각이 같은 쪽 조각에 들어 있는 비율의 평균. 글이 적은 쪽은 세지 않는다."""
    scores = []
    for piece, page_text in zip(pieces, page_texts):
        expected = _shingles(page_text)
        if len(expected) < _FIT_MIN_SHINGLES:
            continue
        scores.append(len(expected & _shingles(piece)) / len(expected))
    return sum(scores) / len(scores) if scores else 0.0


def split_text_for_preview(text: str, page_map: list | None, page_texts: list[str]) -> list[str] | None:
    """원문 대조 탭이 미리보기 PDF 와 함께 넘길 쪽별 파싱 본문.

    두 방식으로 나눠 보고 미리보기 쪽 글과 더 잘 맞는 쪽을 쓴다. 하나는 처리 때 저장한 page_map 이고, 다른 하나는
    미리보기 쪽 첫머리를 본문에서 찾는 split_text_by_pages 다. 예전에는 첫머리 찾기만 썼는데, 쪽 머리말이 본문에
    없거나 목차처럼 글 순서가 다른 쪽에서 경계를 놓치면 그 쪽이 비고 내용이 앞 쪽에 몰렸다(항만수요예측 결과보고서
    5쪽에 목차가 나왔다, 2026-11-25). 반대로 쪽 맞춤이 실패한 문서나 XLSX 처럼 page_map 이 한 쪽뿐인 문서는
    첫머리 찾기가 낫다. 같은 표가 되풀이되는 문서는 맞춤 나누기(split_text_by_alignment)가 낫다."""
    if text and len(page_texts) == 1:
        # 쪽이 하나면 본문 전체가 그 쪽이다(시트 하나인 엑셀 등). 나누는 방식들은 두 쪽 이상에서만 답을 낸다
        return [text]
    splits = (
        pages_from_page_map(text, page_map, len(page_texts)),
        split_text_by_pages(text, page_texts),
        split_text_by_alignment(text, page_texts),
        split_text_by_global_alignment(text, page_texts),
    )
    from app.services.page_boundaries import refine_boundaries

    candidates = [pieces for pieces in splits if pieces is not None]
    if not candidates:
        return None
    # 문서 전체로 가장 잘 맞는 방식을 바탕으로, 쪽 경계마다 모든 방식의 위치와 둘레 문단 경계 가운데 더 맞는 곳을 고른다
    best = refine_boundaries(max(candidates, key=lambda pieces: _page_fit(pieces, page_texts)), candidates, page_texts)
    moved = move_edge_tables(best, page_texts)
    return moved if _page_fit(moved, page_texts) >= _page_fit(best, page_texts) else best


# 쪽 끝 표를 옆 쪽으로 옮기려면 옆 쪽 글과 이만큼 더 맞고, 옆 쪽 글과 이 비율 이상 맞아야 한다
_EDGE_TABLE_MARGIN = 0.2
_EDGE_TABLE_MIN_SHARE = 0.5


def _blocks(piece: str) -> list[str]:
    """쪽 조각을 빈 줄로 나눈 덩어리(빈 줄은 앞 덩어리에 붙인다). 이어 붙이면 조각 그대로다."""
    parts = re.split(r"(?<=\n\n)", piece)
    return [part for part in parts if part]


def _is_table_block(block: str) -> bool:
    return any(line.lstrip().startswith("|") for line in block.splitlines())


def _share_in(block: str, page_shingles: set[str]) -> float:
    grams = _shingles(block)
    return len(grams & page_shingles) / len(grams) if grams else 0.0


def _belongs_next(block: str, here: set[str], there: set[str]) -> bool:
    if not _is_table_block(block) or len(_shingles(block)) < _FIT_MIN_SHINGLES:
        return False
    share_there = _share_in(block, there)
    return share_there >= _EDGE_TABLE_MIN_SHARE and share_there >= _share_in(block, here) + _EDGE_TABLE_MARGIN


def move_edge_tables(pieces: list[str], page_texts: list[str]) -> list[str]:
    """쪽 경계에 걸린 표 덩어리를 원본에서 그 표가 놓인 쪽으로 옮긴 새 조각 목록. 조각을 이으면 본문 그대로다.

    한글·워드의 위치가 정해진 표(글 앞으로 띄운 표)는 미리보기 PDF 글자 층에서 쪽 글 끝에 나와, 쪽 첫머리 맞춤이
    그 표를 앞 쪽 끝에 붙였다(컨설팅 HWP 14쪽 위의 [표 4] 가 13쪽에 나왔다, 2026-11-26). 경계 앞 조각의 마지막 표
    덩어리가 다음 쪽 원본 글과 더 맞으면 다음 조각 앞으로, 경계 뒤 조각의 첫 표 덩어리가 앞 쪽 원본 글과 더 맞으면
    앞 조각 끝으로 옮긴다."""
    out = list(pieces)
    shingles = [_shingles(page_text) for page_text in page_texts]
    for i in range(len(out) - 1):
        here, there = shingles[i], shingles[i + 1]
        blocks = _blocks(out[i])
        moved: list[str] = []
        while len(blocks) > 1 and _belongs_next(blocks[-1], here, there):
            moved.insert(0, blocks.pop())
        if moved:
            out[i], out[i + 1] = "".join(blocks), "".join(moved) + out[i + 1]
            continue
        following = _blocks(out[i + 1])
        pulled: list[str] = []
        while len(following) > 1 and _belongs_next(following[0], there, here):
            pulled.append(following.pop(0))
        if pulled:
            out[i], out[i + 1] = out[i] + "".join(pulled), "".join(following)
    return out
