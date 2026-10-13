"""문서 제목 판정 — 순수 함수 모음(structure_analyze 가 사용).

과거에는 "트리의 첫 HEADING 블록"을 제목으로 삼아, 표지의 연도·머리글·장 제목("2025", "1. 사업개요")이
제목이 되고 제목이 여러 줄이면 첫 줄만 남았다. 지금은 있는 신호를 순서대로 쓴다:

1. 원본 파일이 가진 제목 속성(PDF info dict / DOCX core.title) — 쓸 만한 값일 때만
2. 1쪽 표지 줄: 글자 크기 신호 → 제목(heading) 표시 → 짧은 줄 덩어리(문서 종류 어미) 순
3. OCR 문서는 표지가 오인식되기 쉬워, 비슷한 정제 파일명이 있으면 파일명을 쓴다
4. 장 제목("2. 개요")이 아닌 첫 heading, 마지막으로 정제한 파일명
"""
import difflib
import re
from dataclasses import dataclass

_MAX_TITLE_CHARS = 500
_LEAD_WINDOW = 12  # 표지 후보로 보는 앞쪽 줄 수
_MAX_COVER_LINES = 3  # 한 제목으로 합치는 최대 줄 수
_COVER_LINE_MAX_CHARS = 50
_SIZE_RATIO = 0.75  # 가장 큰 글자의 이 비율 이상이면 제목 줄로 본다
_OCR_FILENAME_SIMILARITY = 0.55
_NEAR_FILENAME_SIMILARITY = 0.8  # 표지가 파일명과 이만큼 닮았으면 OCR 여부와 무관하게 파일명이 더 깨끗하다

_DOC_TYPE_SUFFIXES = (
    "보고서", "계획서", "제안서", "소개서", "기준서", "설계서", "명세서", "요약서", "지침서", "백서", "매뉴얼",
    "가이드라인", "가이드", "사례집", "공고문", "공고", "지침", "계획", "방안", "연구", "분석", "현황", "안내",
    "개요", "결과", "전략", "리포트",
)
_KNOWN_EXTENSIONS = ("pdf", "docx", "doc", "hwpx", "hwp", "txt", "pptx", "ppt", "xlsx", "xls", "md", "html")
_GENERIC_EMBEDDED_TITLES = {
    "untitled", "제목 없음", "제목없음", "powerpoint 프레젠테이션", "powerpoint presentation", "document", "slide 1",
}


@dataclass(frozen=True)
class LeadLine:
    """1쪽(또는 문서 앞쪽)의 한 줄 — size 는 글자 크기(pt, 모를 때 None), is_heading 은 레이아웃이 제목류로 본 줄."""
    text: str
    size: float | None = None
    is_heading: bool = False


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _clean_line(text: str) -> str:
    """OCR 이 줄머리에 흘리는 기호(@, ㅣ, |, •)와 공백을 정리한다."""
    return re.sub(r"^[@ㅣ|•·\-–—*#>\s]+", "", _squash(text))


def clean_filename_title(filename: str) -> str:
    """파일명에서 제목 후보를 만든다 — 확장자·날짜/순번 접두·버전/날짜 접미·대괄호 태그를 걷어낸다."""
    name = _squash(filename or "")
    name = re.sub(rf"\.({'|'.join(_KNOWN_EXTENSIONS)})$", "", name, flags=re.IGNORECASE)
    name = re.sub(r"^\[[^\]]*\]\s*", "", name)  # [서울 데이터 펠로우십] 같은 시리즈 태그
    name = _squash(name.replace("_", " "))
    name = re.sub(r"^\d{6,8}\s+", "", name)  # 260416_ 날짜 접두
    name = re.sub(r"^\d{1,2}[.\s]+(?=\S)", "", name)  # 01_ / 1. 순번 접두
    name = re.sub(r"\s*\[\d{4,8}\]$", "", name)  # [240709] 날짜 접미
    name = re.sub(r"\s+[vV]\d+(\.\d+)*$", "", name)  # v1.0 버전 접미
    name = re.sub(r"\s+\d{6,8}$", "", name)  # _20260211 날짜 접미
    return _squash(name)


def _readable_ratio(text: str) -> float:
    if not text:
        return 0.0
    readable = sum(1 for ch in text if re.match(r"[가-힣A-Za-z0-9 .,\-_()\[\]/&:·'\"~+™®]", ch))
    return readable / len(text)


def is_usable_embedded_title(title: str | None, filename: str) -> bool:
    """파일 속성의 제목이 사람이 읽을 만한 제목인지 — 'PowerPoint 프레젠테이션', '4', 깨진 문자, 파일명 같은 값은 거른다."""
    text = _squash(title or "")
    if len(text) < 3 or not re.search(r"[A-Za-z가-힣]", text):
        return False
    lowered = text.lower()
    if lowered in _GENERIC_EMBEDDED_TITLES or lowered.startswith(
        ("microsoft word", "microsoft powerpoint", "microsoft excel")
    ):
        return False
    if re.search(rf"\.({'|'.join(_KNOWN_EXTENSIONS)})$", lowered):
        return False
    return _readable_ratio(text) >= 0.85


def _ends_with_doc_type(text: str) -> bool:
    stripped = re.sub(r"[\s)\]』」>〉》.:·\-–]+$", "", text)
    stripped = re.sub(r"\s*[vV]?\d+(\.\d+)*$", "", stripped)
    return stripped.endswith(_DOC_TYPE_SUFFIXES)


def _is_noise(text: str) -> bool:
    """제목이 될 수 없는 줄 — 숫자/기호뿐, 날짜, 공고·문서 번호, 버전, URL."""
    if not re.search(r"[A-Za-z가-힣]", text):
        return True
    if re.fullmatch(r"\d{4}\s*년(\s*\d{1,2}\s*월(\s*\d{1,2}\s*일)?)?", text):
        return True
    if re.fullmatch(r"[\[(<].*호\s*[\])>]", text):
        return True
    if re.search(r"제\s*\d{2,4}\s*[-–]\s*\S+", text) and len(text) <= 40 and not _ends_with_doc_type(text):
        return True
    if re.fullmatch(r"[vV]\d+(\.\d+)*", text):
        return True
    if re.search(r"https?://|\S+@\S+\.\S+", text):
        return True
    # 슬라이드 불릿/쪽 표시("들어가기 앞서 (1/2) ⚫ …"), 콜론으로 끝나는 설명 줄, 목차 표지
    if re.search(r"[⚫●■□◦▪▶◆]|\(\d+/\d+\)", text) or text.endswith(":"):
        return True
    return bool(re.fullmatch(r"[<\[(]?\s*(목\s*차|차\s*례|contents)\s*[>\])]?", text, flags=re.IGNORECASE))


def _is_sentence(text: str) -> bool:
    return bool(re.search(r"(니다|이다|한다|된다)\.?$|[.。]$", text))


def _is_chapter_heading(text: str) -> bool:
    return bool(re.match(r"^\s*(\d+[.)]|[IVX]+\.|[Ⅰ-Ⅻ]\.?|제\s*\d+\s*[장절]|[가-하][.)])\s*\S", text))


def _join(lines: list[LeadLine]) -> str:
    return _squash(" ".join(line.text for line in lines))[:_MAX_TITLE_CHARS]


def _cover_title(lead_lines: list[LeadLine]) -> str | None:
    cleaned = []
    for line in lead_lines:
        text = _clean_line(line.text)
        if not text or _is_noise(text):
            continue
        if _is_chapter_heading(text):
            # 장 제목("1. 사업개요", "Ⅳ. 컴포넌트")은 제목이 아니면서 제목 덩어리를 끊는 경계다.
            cleaned.append(LeadLine(text=text))
            continue
        cleaned.append(LeadLine(text=text, size=line.size, is_heading=line.is_heading))
    cleaned = cleaned[:_LEAD_WINDOW]
    if not cleaned:
        return None

    # 1) 글자 크기 신호: 가장 큰 글자(의 75% 이상)가 이어진 줄들이 제목
    sized = [line for line in cleaned if line.size]
    if len(sized) >= 2:
        threshold = max(line.size for line in sized) * _SIZE_RATIO
        run: list[LeadLine] = []
        for line in cleaned:
            if line.size and line.size >= threshold:
                run.append(line)
            elif run:
                break
        if run:
            return _join(run[:_MAX_COVER_LINES])

    # 2) 레이아웃의 제목 표시: 연속한 heading 덩어리 중 문서 종류 어미로 끝나는 것을 우선
    if any(line.is_heading for line in cleaned):
        groups: list[list[LeadLine]] = []
        previous_index = -2
        for index, line in enumerate(cleaned):
            if not line.is_heading:
                continue
            if index == previous_index + 1 and groups:
                groups[-1].append(line)
            else:
                groups.append([line])
            previous_index = index
        for group in groups:
            # 덩어리 앞쪽 줄만으로도 어미를 본다 — 잡음 줄이 빠지며 기관명 줄이 뒤에 붙어도 제목 줄을 놓치지 않게.
            for size in range(1, min(len(group), _MAX_COVER_LINES) + 1):
                if _ends_with_doc_type(_join(group[:size])):
                    return _join(group[:size])
        return _join(groups[0][:_MAX_COVER_LINES])

    # 3) 신호가 없는 문서(HWPX 등): 맨 앞 짧은 줄 덩어리, 아니면 문서 종류 어미로 끝나는 짧은 줄
    body = [line for line in cleaned if not _is_chapter_heading(line.text)]
    block: list[LeadLine] = []
    for line in body:
        if len(line.text) > _COVER_LINE_MAX_CHARS or _is_sentence(line.text):
            break
        block.append(line)
        if len(block) == _MAX_COVER_LINES:
            break
    if block and _ends_with_doc_type(_join(block)):
        return _join(block)
    for line in body[:6]:
        if len(line.text) <= _COVER_LINE_MAX_CHARS + 10 and not _is_sentence(line.text) and _ends_with_doc_type(line.text):
            return line.text
    return None


def _letters(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]", "", text).lower()


def _similarity(a: str, b: str) -> float:
    a, b = re.sub(r"\s+", "", a), re.sub(r"\s+", "", b)
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio() if a and b else 0.0


def resolve_title(
    lead_lines: list[LeadLine],
    *,
    filename: str,
    embedded_title: str | None = None,
    ocr_used: bool = False,
    fallback_heading: str | None = None,
) -> str | None:
    """문서 제목을 정한다. 신호가 하나도 없으면 None."""
    file_title = clean_filename_title(filename)

    if is_usable_embedded_title(embedded_title, filename):
        return _squash(embedded_title)[:_MAX_TITLE_CHARS]

    def prefer_filename_if_ocr_damaged(candidate: str) -> str:
        if not file_title:
            return candidate
        core_title = re.sub(r"\s*[(\[][^)\]]*[)\]]$", "", file_title) or file_title  # (요약본) 같은 꼬리표는 비교에서 뺀다
        candidate_letters, core_letters = _letters(candidate), _letters(core_title)
        is_part_of_filename = candidate_letters in core_letters  # 같거나, 표지가 파일명의 일부("…공고" ⊂ "…공고문")
        has_filename_inside = core_letters in candidate_letters and not ocr_used  # OCR 표지는 앞뒤에 잡음이 붙을 수 있다
        if is_part_of_filename or has_filename_inside:
            return candidate  # 기호·띄어쓰기만 다르거나 한쪽이 다른 쪽의 일부면 표지 표기가 더 정확하다
        similarity = _similarity(candidate, core_title)
        if ocr_used and similarity >= _OCR_FILENAME_SIMILARITY:
            return file_title
        # 글자 수가 거의 같은데 몇 글자만 다르면 오인식이다 — 길이가 크게 다르면 파일명이 줄여 쓴 이름일 뿐이다.
        length_gap = abs(len(_letters(candidate)) - len(_letters(core_title)))
        if similarity >= _NEAR_FILENAME_SIMILARITY and length_gap <= 0.15 * len(_letters(core_title)):
            return file_title
        return candidate

    cover = _cover_title(lead_lines)
    if cover:
        return prefer_filename_if_ocr_damaged(cover)

    heading = _clean_line(fallback_heading or "")
    if heading and not _is_noise(heading) and not _is_chapter_heading(heading):
        return prefer_filename_if_ocr_damaged(heading[:_MAX_TITLE_CHARS])

    return file_title or None
