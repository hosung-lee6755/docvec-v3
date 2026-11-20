"""Docling 요소로 만든 구조 블록을 다듬는다(2026-11-13 구조 탭 정확도 점검).

Docling은 제목(section_header)의 레벨을 모두 1로 주고, 목차 쪽의 줄을 제목으로, 쪽 가장자리의
머리말을 본문으로, 글리프 조각("㔕" 같은 한 글자)을 문단으로 내보낸다. 그대로 쓰면 구조 탭의
트리가 평평하고, 청크의 절 경로도 깊이가 1이라 상위 절 문맥(Parent Retrieval)이 생기지 않는다.

여기서는 요소의 bbox만으로 다음을 보정한다.
1. 제목 레벨: bbox 높이와 '너비 ÷ 글자 수'의 기하평균으로 글자 크기를 추정해 층을 나눈다.
   여러 줄 제목은 높이가 줄 수만큼 커지고 너비 추정은 줄 수만큼 작아져 기하평균에서 상쇄된다.
2. 목차: 목차 요소가 있는 쪽의 제목, 문단, 목록 항목 가운데 같은 문구가 다른 쪽에서 제목으로 나오면 목차 항목이다.
3. 머리말과 꼬리말: 쪽 위아래 가장자리에 있고 세 쪽 이상에서 반복되는 문구다.
   본문 안에서 반복되는 라벨("[모범 사례]")은 의미가 있으므로 건드리지 않는다.
4. 한 글자 문단은 버린다.
"""
import re
from collections import defaultdict

from app.pipeline.blocks.toc_detection import titled_toc_indices

Block = tuple  # (node_type, level, span_start, span_end, text, layout)

# 글자 크기 추정값이 이 비율 안에 있으면 같은 층으로 본다
_TIER_TOLERANCE = 0.08
# 쪽 위아래 가장자리로 보는 범위(문서 전체 요소의 y 범위 대비)
_MARGIN_BAND = 0.07
_REPEAT_MIN_PAGES = 3
# 목차 쪽에서 목차 항목으로 바꿀 수 있는 블록(Docling은 목차 줄을 제목이나 일반 문단으로 낸다)
_TOC_CANDIDATE_TYPES = {"HEADING", "PARAGRAPH", "LIST_ITEM"}
_REPEAT_MAX_CHARS = 80
_DIGITS_RE = re.compile(r"\d+")
_SPACE_RE = re.compile(r"\s+")


def _visual_len(text: str) -> float:
    """글자 폭 합계를 글자 크기 단위로 어림한다. 한글, 한자는 1, 영문과 숫자는 0.55, 공백과 기호는 0.3."""
    total = 0.0
    for ch in text:
        if ch.isspace() or not ch.isalnum():
            total += 0.3
        elif ch.isascii():
            total += 0.55
        else:
            total += 1.0
    return total


def estimate_font_size(text: str, bbox) -> float | None:
    if not bbox or len(bbox) != 4 or not text.strip():
        return None
    width = abs(bbox[2] - bbox[0])
    height = abs(bbox[1] - bbox[3])
    length = _visual_len(text.strip())
    if width <= 0 or height <= 0 or length <= 0:
        return None
    return (height * width / length) ** 0.5


_KMEANS_ROUNDS = 30
# 실제 글자 크기로 층을 나눌 때 기준으로 삼는 크기의 최소 반복 횟수와 최소 비율
_MEASURED_MIN_REPEATS = 2
_MEASURED_MIN_SHARE = 0.01


def _kmeans_1d(values: list[float], k: int) -> list[float]:
    """1차원 k-평균의 중심(큰 것부터). 시작점은 분위수라 결과가 매번 같다."""
    ordered = sorted(values)
    centers = [ordered[min(len(ordered) - 1, int((i + 0.5) * len(ordered) / k))] for i in range(k)]
    for _ in range(_KMEANS_ROUNDS):
        groups: list[list[float]] = [[] for _ in centers]
        for v in values:
            groups[min(range(len(centers)), key=lambda i: abs(v - centers[i]))].append(v)
        updated = [sum(g) / len(g) if g else c for g, c in zip(groups, centers)]
        if updated == centers:
            break
        centers = updated
    return sorted(set(centers), reverse=True)


def assign_tiers(sizes: list[float], max_level: int) -> dict[float, int]:
    """크기를 로그 척도에서 최대 max_level개 무리로 나눠 크기 → 레벨(큰 무리가 1) 지도를 돌려준다.
    추정 크기는 층이 깔끔히 끊기지 않고 퍼져 있어(2026-11-13 실측) 일정 간격으로 자르면 층이 너무 많아진다.
    중심이 _TIER_TOLERANCE 안으로 가까운 무리는 합친다."""
    import math

    logs = [math.log(s) for s in sizes]
    centers = _kmeans_1d(logs, min(max_level, len(set(logs))))
    merged: list[float] = []
    for c in centers:
        if not merged or merged[-1] - c > math.log(1 + _TIER_TOLERANCE):
            merged.append(c)
    return {
        s: 1 + min(range(len(merged)), key=lambda i: abs(math.log(s) - merged[i]))
        for s in set(sizes)
    }


def assign_measured_tiers(sizes: list[float], max_level: int) -> dict[float, int]:
    """원본 텍스트 레이어에서 읽은 실제 글자 크기로 층을 나눈다.

    실제 크기는 값이 몇 개로 딱 떨어지므로 서로 다른 크기마다 한 표만 주고 k-평균을 돌린다. 표지에만 한 번 나오는
    큰 글자(42pt 등)가 1단계를 차지해 본문 제목층이 한 무리로 뭉치지 않도록, 제목 전체의 1% 이상이면서 두 번
    이상 나온 크기만 층의 기준으로 삼는다. 나머지 크기는 가장 가까운 층에 붙는다(2026-11-20, Pub120bk 의
    18/12/10pt 가 1/2/3단계로 나뉜다)."""
    import math
    from collections import Counter

    counts = Counter(sizes)
    floor = max(_MEASURED_MIN_REPEATS, _MEASURED_MIN_SHARE * len(sizes))
    basis = sorted({math.log(s) for s, c in counts.items() if c >= floor} or {math.log(s) for s in counts})
    centers = _kmeans_1d(basis, min(max_level, len(basis)))
    merged: list[float] = []
    for c in centers:
        if not merged or merged[-1] - c > math.log(1 + _TIER_TOLERANCE):
            merged.append(c)
    # 기준층이 모자라면 기준층보다 확실히 큰 크기를 맨 위층으로 더한다(드문 큰 제목이 본문 제목과 묶이지 않게)
    largest = math.log(max(counts))
    if len(merged) < max_level and largest - merged[0] > math.log(1 + _TIER_TOLERANCE):
        merged.insert(0, largest)
    smallest = math.log(min(counts))
    if len(merged) < max_level and merged[-1] - smallest > math.log(1 + _TIER_TOLERANCE):
        merged.append(smallest)
    return {
        s: 1 + min(range(len(merged)), key=lambda i: abs(math.log(s) - merged[i]))
        for s in counts
    }


def _norm(text: str) -> str:
    return _SPACE_RE.sub("", text)


def _refine_levels(blocks: list[list], sizes: list[float | None], max_level: int, measured: bool = False) -> None:
    known = [s for s, b in zip(sizes, blocks) if s is not None and b[0] == "HEADING"]
    if len({round(s, 1) for s in known}) < 2:
        return  # 크기 차이가 없으면 Docling 레벨을 그대로 둔다
    level_of = (assign_measured_tiers if measured else assign_tiers)(known, max_level)
    previous = 1
    for block, size in zip(blocks, sizes):
        if block[0] != "HEADING":
            continue
        block[1] = level_of[size] if size is not None else previous
        previous = block[1]


def _mark_toc_entries(blocks: list[list], elements: list[dict]) -> None:
    # Docling이 목차 요소를 내지 않아도 "목차"/"차례" 제목 뒤 항목이 본문에 다시 나오면 목차다(2026-11-17)
    for index in titled_toc_indices([block[4] for block in blocks]):
        if blocks[index][0] in _TOC_CANDIDATE_TYPES:
            blocks[index][0], blocks[index][1] = "TOC", None
    toc_pages = {el.get("page") for el in elements if el.get("type") == "document_index"}
    if not toc_pages:
        return
    later_headings: set[str] = set()
    for block in blocks:
        if block[0] == "HEADING" and (block[5] or {}).get("page_number") not in toc_pages:
            later_headings.add(_norm(block[4]))
    for block in blocks:
        page = (block[5] or {}).get("page_number")
        if block[0] in _TOC_CANDIDATE_TYPES and page in toc_pages and _norm(block[4]) in later_headings:
            block[0], block[1] = "TOC", None


def _mark_running_headers(blocks: list[list], elements: list[dict]) -> None:
    ys = [y for el in elements if el.get("bbox") and len(el["bbox"]) == 4 for y in (el["bbox"][1], el["bbox"][3])]
    if not ys:
        return
    low, high = min(ys), max(ys)
    band = (high - low) * _MARGIN_BAND
    if band <= 0:
        return
    bbox_by_id = {el.get("id"): el.get("bbox") for el in elements}

    def edge(block) -> str | None:
        bbox = bbox_by_id.get((block[5] or {}).get("element_id"))
        if not bbox or len(bbox) != 4:
            return None
        top, bottom = max(bbox[1], bbox[3]), min(bbox[1], bbox[3])
        if top >= high - band:
            return "HEADER"
        if bottom <= low + band:
            return "FOOTER"
        return None

    pages_by_text: dict[tuple[str, str], set] = defaultdict(set)
    keys = []
    for block in blocks:
        kind = edge(block) if block[0] in ("PARAGRAPH", "HEADING") and len(block[4]) <= _REPEAT_MAX_CHARS else None
        key = (kind, _DIGITS_RE.sub("#", _norm(block[4]))) if kind else None
        keys.append(key)
        if key:
            pages_by_text[key].add((block[5] or {}).get("page_number"))
    for block, key in zip(blocks, keys):
        if key and len(pages_by_text[key]) >= _REPEAT_MIN_PAGES:
            block[0], block[1] = key[0], None


# 한국 공문서의 제목 기호 순서(작을수록 상위). 같은 크기의 제목이면 이 순서로 단계를 나눈다.
# "1.1" 같은 하위 번호는 순서를 정하지 않는다(글자 크기로만 판단).
_MARKER_RANKS = (
    (re.compile(r"^\s*(?:제\s*\d+\s*[장편부절]|[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+\s*[.\s]|\d+\s*\.(?!\d)|PART\s*\d+)", re.IGNORECASE), 0),
    (re.compile(r"^\s*[□■]"), 1),
    (re.compile(r"^\s*[○◦●◎❍]"), 2),
    (re.compile(r"^\s*[-–·•※▷▶☞]"), 3),
)


def _marker_rank(text: str) -> int | None:
    for pattern, rank in _MARKER_RANKS:
        if pattern.match(text):
            return rank
    return None


_CHAPTER_NUMBER_RE = re.compile(r"^\s*(\d+)\s*\.(?!\d)")


def _chapter_number(text: str) -> int | None:
    match = _CHAPTER_NUMBER_RE.match(text)
    return int(match.group(1)) if match else None


def _similar_size(size: float | None, other: float | None) -> bool:
    if size is None or other is None:
        return True
    return max(size, other) <= min(size, other) * (1 + _TIER_TOLERANCE)


def _apply_marker_order(blocks: list[list], sizes: list[float | None], max_level: int) -> None:
    """같은 크기인데 더 하위 기호를 단 제목이 상위 기호 제목과 같거나 높은 단계면 한 단계 내린다.

    디지털협업공장 공고문(2026-11-20)에서 "1. 사업 개요"와 바로 아래 "□ 사업 개요"가 같은 10.7pt 라
    □ 제목이 장 제목과 같은 단계(또는 위)로 잡혀 청크 절 경로에서 장 제목이 빠졌다."""
    recent: dict[int, tuple[int, float | None]] = {}
    last_numbered: tuple[int, int, float | None] | None = None  # (번호, 단계, 크기)
    for block, size in zip(blocks, sizes):
        if block[0] != "HEADING" or block[1] is None:
            continue
        rank = _marker_rank(block[4])
        if rank is None:
            continue
        number = _chapter_number(block[4])
        if number is not None:
            # "6." 다음 "7." 처럼 번호가 이어지고 크기가 비슷하면 같은 단계다. 자율형공장 공고문(2026-11-20)은
            # 1~6장을 16pt, 7~8장을 15pt 로 써서 7장이 6장 아래로 들어갔다.
            if last_numbered and number == last_numbered[0] + 1 and _similar_size(size, last_numbered[2]):
                block[1] = last_numbered[1]
            last_numbered = (number, block[1], size)
        upper = [r for r in recent if r < rank]
        if upper:
            parent_level, parent_size = recent[max(upper)]
            not_larger = size is None or parent_size is None or size <= parent_size * (1 + _TIER_TOLERANCE)
            if block[1] <= parent_level and not_larger:
                block[1] = min(parent_level + 1, max_level)
        recent = {r: v for r, v in recent.items() if r < rank}
        recent[rank] = (block[1], size)


_FONT_TIER_LIMIT = 3

# "3.", "3.2", "3.2.1" 같은 점 번호. 마디는 1~99 이고 번호 뒤에 공백과 글이 이어져야 한다(날짜·수치 제외)
_DECIMAL_NUMBER_RE = re.compile(r"^\s*([1-9]\d?(?:\.[1-9]\d?)*)\.?\s+\S")
_DECIMAL_MIN_SUB_HEADINGS = 2
# 번호 장을 묶는 제목("해설 2.", "부록 1", "붙임 3", "PART 2"). 그 아래 번호는 1부터 다시 시작한다
_CONTAINER_RE = re.compile(r"^\s*(?:해설|부록|별첨|붙임|PART|Part)\s*\d+")


def _decimal_number(text: str) -> tuple[int, ...] | None:
    match = _DECIMAL_NUMBER_RE.match(text)
    if not match:
        return None
    number = match.group(1)
    if "." not in number and not re.match(r"^\s*\d+\.", text):
        return None  # "1 개요" 처럼 점이 없는 한 마디 번호는 제목 번호로 보지 않는다
    return tuple(int(part) for part in number.split("."))


def _decimal_trees(blocks: list[list]) -> dict[int, int | None]:
    """번호의 부모-자식 관계가 이어지는 제목만 고른다. 돌려주는 값은 블록 위치 → 부모 블록 위치(뿌리는 None).

    "3.2.1"의 부모는 그 앞에 가장 가까이 나온 "3.2"다. 자식 번호가 하나도 없는 "5. 문화 및 집회시설" 같은
    표·별표 속 번호 항목은 고르지 않는다(기계설비 매뉴얼, 2026-11-20)."""
    last_seen: dict[tuple[int, ...], int] = {}
    parent_of: dict[int, int | None] = {}
    for index, block in enumerate(blocks):
        if block[0] != "HEADING" or block[1] is None:
            continue
        if _CONTAINER_RE.match(block[4]):
            last_seen = {}  # "해설 2." 아래 번호는 앞 묶음의 번호와 이어지지 않는다
            continue
        number = _decimal_number(block[4])
        if number is None:
            continue
        parent = last_seen.get(number[:-1]) if len(number) > 1 else None
        if parent is not None:
            parent_of[index] = parent
            parent_of.setdefault(parent, None)
        last_seen[number] = index
        # 같은 번호대가 다시 시작하면(새 장) 그보다 깊은 번호는 더 이상 부모가 될 수 없다
        for key in [k for k in last_seen if len(k) > len(number) and k[: len(number)] != number]:
            del last_seen[key]
    return parent_of


def _apply_decimal_depth(blocks: list[list], max_level: int) -> None:
    """점 번호 깊이로 단계를 정한다("3." < "3.2" < "3.2.1").

    KRS SG 0027 같은 규격 문서(2026-11-20)는 장·절·항 제목을 모두 같은 크기로 써서 글자 크기로는 단계가
    나뉘지 않는다. 번호의 부모-자식 관계가 두 번 이상 이어지는 문서에만 적용한다. 뿌리 제목은 지금 단계를
    두되, 문서에서 가장 깊은 번호까지 max_level 안에 들어가도록 필요하면 위로 올린다. 자식은 부모 바로 아래다."""
    parent_of = _decimal_trees(blocks)
    if sum(1 for parent in parent_of.values() if parent is not None) < _DECIMAL_MIN_SUB_HEADINGS:
        return

    def depth(index: int) -> int:
        steps = 0
        while parent_of.get(index) is not None:
            index, steps = parent_of[index], steps + 1
        return steps

    deepest = min(max(depth(i) for i in parent_of) + 1, max_level)
    # 뿌리를 올리는 기준은 글자 크기 단계 수다. 상한(5)으로 재면 3단계 문서의 장 제목이 3단계에 머문다
    ceiling = max(1, min(max_level, _FONT_TIER_LIMIT) - deepest + 1)
    original = {i: b[1] for i, b in enumerate(blocks)}
    for index in sorted(parent_of):
        parent = parent_of[index]
        if parent is None:
            blocks[index][1] = min(blocks[index][1], ceiling)
        else:
            blocks[index][1] = min(max_level, blocks[parent][1] + 1)
    _align_childless_chapters(blocks, parent_of, original)
    _nest_under_containers(blocks, parent_of, original, depth, max_level)


def _nest_under_containers(blocks: list[list], parent_of: dict, original: dict, depth, max_level: int) -> None:
    """"해설 2." 같은 묶음 제목 아래 번호 장·절이 있으면 묶음을 장보다 한 단계 위에 둔다.

    KR S-03010(2026-11-20): 본문 장을 1단계로 올리자 3단계이던 "해설 2."가 그 아래 "1. 전기식 선로전환기"보다
    낮아져 절 경로에서 빠졌다. 묶음 제목은 모두 같은 단계로 둔다."""
    heading_indices = [i for i, b in enumerate(blocks) if b[0] == "HEADING" and b[1] is not None]
    containers = [i for i in heading_indices if _CONTAINER_RE.match(blocks[i][4])]
    scopes: dict[int, list[int]] = {}
    for position, container in enumerate(containers):
        end = containers[position + 1] if position + 1 < len(containers) else len(blocks)
        members = [
            i for i in heading_indices if container < i < end
            and (number := _decimal_number(blocks[i][4])) is not None and (i in parent_of or len(number) == 1)
        ]
        if members:
            scopes[container] = members
    if not scopes:
        return
    needed = max(depth(i) if i in parent_of else 0 for members in scopes.values() for i in members) + 1
    container_level = max(1, min(min(original[c] for c in scopes), min(max_level, _FONT_TIER_LIMIT) - needed))
    for container, members in scopes.items():
        blocks[container][1] = container_level
        for i in members:
            blocks[i][1] = min(max_level, container_level + 1 + (depth(i) if i in parent_of else 0))


def _align_childless_chapters(blocks: list[list], parent_of: dict[int, int | None], original: dict) -> None:
    """하위 절이 없는 장("5. 표시 및 포장")도 바로 앞 장과 번호가 이어지고 원래 단계가 같으면 같은 단계로 둔다."""
    chapters = [
        (index, number[0]) for index, block in enumerate(blocks)
        if block[0] == "HEADING" and block[1] is not None
        and (number := _decimal_number(block[4])) is not None and len(number) == 1
    ]
    # 앞 장을 따르고("4." 다음 "5."), 첫 장처럼 앞 장이 없으면 뒤 장을 따른다("1." 다음 "2.")
    for ordered, step in ((chapters, 1), (list(reversed(chapters)), -1)):
        previous: tuple[int, int, int] | None = None  # (장 번호, 원래 단계, 새 단계)
        for index, chapter in ordered:
            if (index not in parent_of and previous and chapter == previous[0] + step
                    and original[index] == previous[1]):
                blocks[index][1] = previous[2]
            previous = (chapter, original[index], blocks[index][1])


def refine_element_blocks(
    blocks: list[Block], elements: list[dict], max_level: int = 3, font_sizes: dict[str, float] | None = None,
) -> list[Block]:
    """`_build_blocks_from_elements()`의 결과를 보정한 새 목록을 돌려준다(입력은 바꾸지 않는다).

    font_sizes 는 원본 PDF 텍스트 레이어에서 읽은 제목의 실제 글자 크기다(pdf_heading_fonts). 없으면 bbox 로 어림한다."""
    bbox_by_id = {el.get("id"): el.get("bbox") for el in elements}
    font_sizes = font_sizes or {}
    work = [list(b) for b in blocks if not (b[0] == "PARAGRAPH" and len(b[4].strip()) <= 1)]
    _mark_toc_entries(work, elements)
    _mark_running_headers(work, elements)

    def size_of(block) -> float | None:
        element_id = (block[5] or {}).get("element_id")
        if font_sizes:  # 실제 크기와 어림값은 척도가 달라 섞지 않는다. 못 읽은 제목은 앞 제목의 단계를 따른다
            return font_sizes.get(element_id)
        return estimate_font_size(block[4], bbox_by_id.get(element_id))

    sizes = [size_of(b) if b[0] == "HEADING" else None for b in work]
    # 글자 크기 무리는 많아야 세 개로 나눈다. 상한을 5로 올리자 표지 제목 같은 드문 큰 글자가 1·2단계를 차지해
    # 장 제목이 3~4단계로 밀려났다(기계설비 매뉴얼 1단계 595개 → 3개, 2026-11-20). 더 깊은 단계는 번호와 기호 순서로만 내린다
    _refine_levels(work, sizes, min(max_level, _FONT_TIER_LIMIT), measured=bool(font_sizes))
    _apply_marker_order(work, sizes, max_level)
    _apply_decimal_depth(work, max_level)
    return [tuple(b) for b in work]
