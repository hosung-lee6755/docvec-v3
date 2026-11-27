"""구조 분석 블록: 문서 구조 트리 — 통합 설계서 §3.3⑤ / 문서 파싱 고도화 Phase 2.

`Document.extraction_layout`(어댑터가 노출하는 줄 단위 폰트/위치 신호 — PDF/
DOCX만, HWP/HWPX와 업그레이드 전 문서는 없음)이 있으면 그것을 헤더/제목
판별의 보강 신호로 쓰고, 없으면 순수 텍스트 휴리스틱(번호/기호 패턴 + 줄
단위 분류)만으로 폴백한다 — 두 경로 모두 같은 함수 안에서 분기할 뿐, 별도
블록 타입이나 버전으로 나뉘지 않는다. 정규식이 뭔가를 분류해내면 그 판단이
항상 우선이고(오탐 방지), 정규식이 아무것도 찾지 못했을 때만 폰트 신호(굵고
본문보다 뚜렷이 큰 글자)로 제목을 승격한다.

문단 경계를 빈 줄(두 줄바꿈)로만 판단하지 않는다 — pdf_adapter의 네이티브
추출 경로(pdfplumber.Page.extract_text())는 글자만 좌표순으로 이어붙일 뿐
문단 사이 빈 줄을 보존하지 않으므로(스캔 문서를 OCR한 결과만 우연히 빈
줄을 남긴다), 빈 줄에만 의존하면 네이티브 추출 문서 전체가 항상 문단 1개로
묶여버린다. 대신 각 줄을 개별적으로 분류해 제목/목록 줄에서 문단을 끊고,
연속된 본문 줄만 하나의 PARAGRAPH로 병합한다(빈 줄이 있으면 그 지점에서도
끊는다 — OCR 등으로 실제 빈 줄이 있는 경우 더 세밀하게 나뉘는 효과).
"""
import logging
import re
import uuid

from pydantic import BaseModel

from app.pipeline.blocks.base import BaseBlock, BlockContext, BlockResult
from app.pipeline.blocks.content_blocks import _carry, _upstream_text
from app.pipeline.blocks.structure_refine import refine_element_blocks
from app.pipeline.blocks.title_box import shifted_level, starts_with_roman, title_box_heading
from app.pipeline.blocks.legal_structure import apply_legal_structure, looks_like_regulation
from app.pipeline.blocks.toc_detection import is_toc_title, titled_toc_indices
from app.pipeline.blocks.title_resolver import LeadLine, _is_chapter_heading, resolve_title

logger = logging.getLogger(__name__)

# 점 번호("1.2 개요")와 붙임표 번호("1-1. 개발 범위")를 함께 받는다. 붙임표 번호는 마디마다 두 자리 이하이고 뒤에 마침표가
# 있을 때만 받는다. 그래야 전화번호(010-1234-5678), 날짜(2026-11-25), 범위("3-4 명")가 제목이 되지 않는다(AIDE 제안서, 2026-11-25)
_HEADING_NUMBERED_RE = re.compile(r"^(\d+(?:\.\d+)*|\d{1,2}(?:-\d{1,2})+(?=\.))[.\)]?\s+\S")
_NUMBER_PARTS_RE = re.compile(r"[.-]")


def _number_depth(number: str) -> int:
    """번호의 마디 수. "1.2"와 "1-2"는 2다."""
    return len(_NUMBER_PARTS_RE.split(number))
_HEADING_KOREAN_RE = re.compile(r"^제\s*\d+\s*[장절조편]")
# 공고문·계획서 hwpx 는 글자 크기 없이 "□ 사업개요" 로 절을 나눈다(한국 공문서 관례).
_HEADING_SQUARE_BULLET_RE = re.compile(r"^□\s*\S")
_LIST_RE = re.compile(r"^([-*•]|\d+[\).])\s+\S")
# 줄 정보의 style_name 가운데 파서가 목록 항목으로 판정한 값(Docling label)
_PARSER_LIST_STYLES = frozenset({"list_item", "list-item"})
# pdf_adapter.py가 표를 만나면 "[표 N]\n{table_text}" 형태로 RawTextBlock을
# 만들고, extraction_blocks.py가 그걸 다른 블록들과 "\n\n"로 이어붙여
# parsed_text를 만든다 — 이 마커 줄이 표의 시작이라는 유일한 신호다. 표의
# 2번째 이후 행("셀1 | 셀2 | ...")은 그 자체로는 표처럼 보이지 않으므로
# _classify로는 구분할 수 없다 — _build_blocks가 첫 줄만 보고 TABLE 누적을
# 시작한 뒤, 뒤따르는 줄은 재분류하지 않고 그대로 이어붙인다.
_TABLE_MARKER_RE = re.compile(r"^\[표\s*\d+\]$")
# 마커의 번호를 뽑아 Document.tables[*]["id"]를 역으로 찾는다(문서 파싱
# 고도화 Phase 3, DocumentNode.source_table_id) — 어댑터가 이 번호를 문서
# 전체에서 순차 부여하므로(pdf_adapter.py의 table_ordinal 주석 참고),
# doc.tables 리스트도 같은 순서로 쌓여 번호-1이 곧 리스트 인덱스가 된다.
_TABLE_MARKER_NUMBER_RE = re.compile(r"^\[표\s*(\d+)\]")
# 목차 항목: "1장 서론 ..... 3" 처럼 점선/공백 리더 뒤에 페이지 번호로 끝나는
# 짧은 줄. 문서 앞부분에서 이런 줄이 연속(_TOC_MIN_RUN개 이상) 나타나면 목차
# 블록으로 본다 — 번호 매김이 붙은 항목("1. 서론 ... 3")은 원래 정규식으로도
# HEADING처럼 보였을 것이므로, 목차로 확정되면 그 판단을 덮어써 문서 구조
# 트리에 가짜 제목이 섞이지 않게 한다.
# 리더는 점(.), 줄임표(…), 가운뎃점(·, ㆍ, ‥), 밑줄과 하이픈, 공백(탭 포함)을 받는다
_TOC_ENTRY_RE = re.compile(r".{2,}[.…·ㆍ‥_\-\s]{3,}\d{1,4}\s*$")
_TOC_MIN_RUN = 3
_TOC_SEARCH_WINDOW = 60
# 정렬 오차 허용 폭 — extraction_layout은 pdfplumber 문자 클러스터링으로,
# parsed_text의 줄 구분은 extract_text() 자체의 줄 나눔으로 각각 독립적으로
# 계산되므로 완전히 1:1로 맞물리지 않을 수 있다. 못 맞춘 줄은 그냥 폰트 신호
# 없이(정규식만으로) 분류되는 것으로 안전하게 성능 저하 없이 넘어간다.
_ALIGN_LOOKAHEAD = 5
# 폰트 신호만으로 제목 승격을 트리거하려면 본문 대표 크기보다 이 정도는 더
# 커야 한다 — 렌더링 지터로 우연히 조금 더 큰 글자가 가짜 제목이 되지 않게.
_HEADING_FONT_DELTA = 2.0
_HEADING_LEVEL1_RATIO = 1.3


def _detect_toc_line_offsets(text: str) -> set[int]:
    """목차 줄의 시작 오프셋. 두 규칙을 합친다.

    - 문서 앞부분에서 "제목 ..... 3" 꼴이 연속 _TOC_MIN_RUN줄 이상 나타나는 경우
    - "목차"/"차례" 제목 뒤 항목이 본문에 다시 나오는 경우(쪽 번호 없는 목차, toc_detection 참고)
    """
    return _leader_toc_offsets(text) | _titled_toc_offsets(text)


def _titled_toc_offsets(text: str) -> set[int]:
    offsets: list[int] = []
    lines: list[str] = []
    offset = 0
    for line in text.split("\n"):
        if line.strip():
            offsets.append(offset)
            lines.append(line)
        offset += len(line) + 1
    return {offsets[i] for i in titled_toc_indices(lines)}


def _leader_toc_offsets(text: str) -> set[int]:
    """문서 앞부분(첫 _TOC_SEARCH_WINDOW개 비어있지 않은 줄 이내)에서 목차
    패턴이 연속 _TOC_MIN_RUN줄 이상 나타나면 그 줄들의 시작 오프셋 집합을
    반환한다. 못 찾으면 빈 집합(목차 없음으로 안전하게 처리)."""
    offset = 0
    non_empty_seen = 0
    run: list[int] = []
    for line in text.split("\n"):
        line_start = offset
        offset += len(line) + 1
        stripped = line.strip()
        if not stripped:
            if len(run) >= _TOC_MIN_RUN:
                return set(run)
            run = []
            continue
        non_empty_seen += 1
        if non_empty_seen > _TOC_SEARCH_WINDOW:
            break
        if _TOC_ENTRY_RE.match(stripped):
            run.append(line_start)
        else:
            if len(run) >= _TOC_MIN_RUN:
                return set(run)
            run = []
    return set(run) if len(run) >= _TOC_MIN_RUN else set()


def _split_multiline_entries(entries: list[dict]) -> list[dict]:
    """여러 줄을 담은 글꼴 항목을 줄마다 같은 글꼴의 항목으로 나눈다. 본문 텍스트는 줄 단위로 짝을 찾으므로,
    나누지 않으면 그런 항목이 몇 개만 이어져도 짝을 잃고 뒤쪽 줄 전체가 글꼴 정보 없이 분류된다
    (HTML 고도화보고서 실측: 1095개 중 144개만 짝지어져 번호 없는 큰 제목이 모두 문단이 됨, 2026-11-19)."""
    split: list[dict] = []
    for entry in entries:
        lines = [line for line in (entry.get("text") or "").split("\n") if line.strip()]
        if len(lines) <= 1:
            split.append(entry)
            continue
        split.extend({**entry, "text": line} for line in lines)
    return split


class _LineLayoutCursor:
    """text.split("\n")로 훑는 줄과 extraction_layout 항목을 순차 정렬한다
    (완전한 문자 오프셋 대조 대신, 작은 lookahead 창 안에서 텍스트가 일치하는
    다음 항목을 찾는 최선 노력 방식 — 표/헤더/푸터처럼 한쪽에만 있는 줄이
    있어도 깨지지 않는다)."""

    def __init__(self, entries: list[dict]):
        self._entries = _split_multiline_entries(entries)
        self._pos = 0

    def match(self, stripped_line: str) -> dict | None:
        if not stripped_line:
            return None
        limit = max(0, min(_ALIGN_LOOKAHEAD, len(self._entries) - self._pos))
        for i in range(limit):
            idx = self._pos + i
            if self._entries[idx]["text"].strip() == stripped_line:
                self._pos = idx + 1
                return self._entries[idx]
        return None


def _resolve_source_table_id(block_text: str, tables: list[dict] | None) -> str | None:
    """A TABLE node's `block_text` starts with the adapter's "[표 N]" marker
    (N assigned sequentially across the whole document — see pdf_adapter.py's
    `table_ordinal`). `tables` (Document.tables) is built by iterating the
    same pages/tables in the same order, so N-1 is directly that list's
    index. Returns None when there's no marker, no tables, or N is out of
    range (e.g. a document processed before source_table_id existed)."""
    if not tables:
        return None
    match = _TABLE_MARKER_NUMBER_RE.match(block_text)
    if not match:
        return None
    index = int(match.group(1)) - 1
    if not (0 <= index < len(tables)):
        return None
    return tables[index].get("id")


def _body_font_size(entries: list[dict]) -> float | None:
    sizes = [round(e["font_size"], 1) for e in entries if e.get("font_size")]
    if not sizes:
        return None
    return max(set(sizes), key=sizes.count)


# 숫자로 시작한다는 이유만으로 제목이 되던 줄을 거른다(2026-11-16 점검). 스캔 PDF와 HWPX의 그림 OCR에서
# 표의 숫자 행("5.07    5.08 ..."), 쪽 머리말("6  2022 ... 분석보고서"), 참고문헌("02 홍길동. (2020). ...")이
# 번호 제목으로 잡혔다.
_HEADING_MAX_CHARS = 50
_DATE_ONLY_RE = re.compile(
    r"^(?:\d{4}\s*년\s*\d{1,2}\s*월(?:\s*\d{1,2}\s*일)?|\d{4}[.\-/]\s*\d{1,2}(?:[.\-/]\s*\d{1,2})?)\.?$"
)
_HEADING_MAX_LEADING_NUMBER = 99
# 서식 끝의 받는 사람 줄("한국해양수산개발원장 귀하")은 크고 굵어도 제목이 아니다(제안요청서, 2026-11-20 감사)
_ADDRESSEE_RE = re.compile(r"\S\s*귀\s*[하중]$")
_WIDE_GAP_RE = re.compile(r"\S {3,}\S|\s\|\s")
# 참고문헌 항목의 출판 연도 "(2020)."
_CITATION_YEAR_RE = re.compile(r"\((?:19|20)\d{2}\)\.")
# 번호 바로 뒤에 또 숫자가 오면 쪽 번호와 연도("8 2022 ... 분석보고서")다
_NUMBER_THEN_NUMBER_RE = re.compile(r"^[.)]?\s*\d{2,}")
# "1)" 꼴 번호는 문서마다 깊이가 달라 장 제목(레벨 1)으로 두면 트리가 무너진다
_PAREN_NUMBER_LEVEL = 3
_REPEATED_LINE_MIN_COUNT = 3
_REPEATED_LINE_MIN_KEY = 8
_REPEATED_LINE_MAX_CHARS = 80
_BULLET_CHARS = set("•◦▪▫○●■□◆◇ㅇ※-*·")
# 쪽의 처음과 끝에서 몇 줄까지를 머리말·꼬리말 후보로 볼지
_PAGE_EDGE_LINES = 2
# 칸 구분선 "|"가 이만큼 있으면 표 행이다. 머리말에 구분선 하나를 쓰는 경우("보고서 | 2022")는 남긴다
_TABLE_ROW_MIN_PIPES = 2
_NON_KEY_RE = re.compile(r"[\d\s]+")


def _is_letter_spaced(stripped: str) -> bool:
    """"1. 목    적"처럼 번호 뒤의 글자를 한 자씩 띄워 쓴 제목인지. 넓은 간격이 있어도 표의 줄이 아니다."""
    tokens = stripped.split()
    return len(tokens) >= 3 and all(len(token) == 1 for token in tokens[1:])


def _plausible_numbered_heading(line: str, number: str) -> bool:
    stripped = line.strip()
    has_wide_gap = bool(_WIDE_GAP_RE.search(stripped)) and not _is_letter_spaced(stripped)
    if len(stripped) > _HEADING_MAX_CHARS or has_wide_gap or _CITATION_YEAR_RE.search(stripped):
        return False
    if int(_NUMBER_PARTS_RE.split(number)[0]) > _HEADING_MAX_LEADING_NUMBER:
        return False
    rest = stripped[stripped.find(number) + len(number):]
    if _NUMBER_THEN_NUMBER_RE.match(rest):
        return False
    # 앞 번호를 뺀 나머지에 글자가 숫자보다 많아야 제목이다("1. 서론"은 제목, "5.07 5.08"은 숫자 행)
    letters = sum(ch.isalpha() for ch in rest)
    digits = sum(ch.isdigit() for ch in rest)
    return letters > digits


def _is_table_line(stripped: str) -> bool:
    return (
        stripped.startswith("|")
        or stripped.count("|") >= _TABLE_ROW_MIN_PIPES
        or bool(_TABLE_MARKER_RE.match(stripped))
    )


def _page_edge_line_starts(text: str, page_map: list | None) -> set[int]:
    """각 쪽의 처음과 끝 몇 줄(빈 줄 제외)의 시작 위치. page_map 항목은 [쪽 끝 위치, 쪽 번호]다.

    쪽 끝을 셀 때는 표 줄("[표 N]" 표시, 칸 구분선 "|"가 있는 행, 표시 바로 다음의 표 제목)을 건너뛴다. 스캔 PDF 는
    쪽의 표 글을 OCR 글 뒤에 붙이므로, 표 줄을 세면 꼬리말이 쪽 끝에서 밀려나 본문으로 남는다(서울 데이터 펠로우십
    보고서, 2026-11-20). HWP 표 행은 맨 앞에 "|"가 없어("요구사항 고유번호 |  | MPR-002") 구분선 개수로 가린다.
    쪽 머리는 예전처럼 모든 줄을 센다. 쪽 머리의 표 다음에 오는 본문 소제목이 머리말로 잡히지 않게 하려는 것이다
    (조사료 지침 "《조사료 장거리 유통비 지원》")."""
    if not page_map or len(page_map) < 2:
        return set()
    starts: list[int] = []
    body_starts: list[int] = []
    offset = 0
    after_marker = False
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped:
            starts.append(offset)
            if not (_is_table_line(stripped) or after_marker):
                body_starts.append(offset)
            after_marker = bool(_TABLE_MARKER_RE.match(stripped))
        offset += len(line) + 1
    edges: set[int] = set()
    page_start = 0
    for entry in page_map:
        page_end = entry[0]
        edges.update([s for s in starts if page_start <= s < page_end][:_PAGE_EDGE_LINES])
        edges.update([s for s in body_starts if page_start <= s < page_end][-_PAGE_EDGE_LINES:])
        page_start = page_end
    return edges


def _running_header_offsets(text: str, page_map: list | None) -> set[int]:
    """쪽 가장자리에 있고, 숫자와 공백을 뺀 내용이 같은 줄이 여러 쪽에 나오면 머리말·꼬리말이다.
    요소 위치 정보가 없는 경로(HWP/HWPX, 스캔 PDF)용이다. 쪽 경계를 모르면 아무것도 표시하지 않는다
    (본문에서 반복되는 "위반 건수 : 2개" 같은 줄을 지우지 않기 위해, 2026-11-16)."""
    edges = _page_edge_line_starts(text, page_map)
    if not edges:
        return set()
    by_key: dict[str, list[int]] = {}
    offset = 0
    for line in text.split("\n"):
        stripped = line.strip()
        # 글머리표 줄("• 위반 건수 : 2개")은 쪽 끝에 와도 본문 목록이다
        is_bullet = stripped[:1] in _BULLET_CHARS or bool(_LIST_RE.match(stripped))
        if offset in edges and stripped and not is_bullet and len(stripped) <= _REPEATED_LINE_MAX_CHARS:
            key = _NON_KEY_RE.sub("", stripped)
            if len(key) >= _REPEATED_LINE_MIN_KEY:
                by_key.setdefault(key, []).append(offset)
        offset += len(line) + 1
    return {o for offsets in by_key.values() if len(offsets) >= _REPEATED_LINE_MIN_COUNT for o in offsets}


def _classify(
    line: str, layout: dict | None, body_font_size: float | None,
) -> tuple[str, int | None]:
    if _TABLE_MARKER_RE.match(line):
        return "TABLE", None
    # 각주 role은 extraction_blocks._detect_header_footer_footnote_lines가
    # 페이지 하단 위치 + 각주 마커 패턴이라는, 여기 정규식보다 더 구체적인
    # 신호로 이미 판정해 둔 결과다 — "1) ..." 같은 각주 표기는 번호매김
    # 정규식(_HEADING_NUMBERED_RE)과도 우연히 일치할 수 있으므로, 각주로
    # 태깅된 줄은 일반 정규식 분류보다 먼저 확정한다.
    if layout and layout.get("role") == "footnote":
        return "FOOTNOTE", None
    # 파서(Docling)가 목록 항목으로 읽은 줄은 번호가 붙어도 제목이 아니다. 목록 기호를 되살린 뒤(2026-11-26)
    # "1. 데이터 파이프라인" 같은 짧은 번호 항목이 아래 번호 제목 규칙에 걸리지 않게 먼저 정한다
    if layout and layout.get("style_name") in _PARSER_LIST_STYLES:
        return "LIST_ITEM", None
    m = _HEADING_NUMBERED_RE.match(line)
    if m and _plausible_numbered_heading(line, m.group(1)):
        if line[len(m.group(1)):].startswith(")"):
            return "HEADING", _PAREN_NUMBER_LEVEL
        level = _number_depth(m.group(1))
        return "HEADING", level
    if _HEADING_KOREAN_RE.match(line):
        return "HEADING", 1
    if _HEADING_SQUARE_BULLET_RE.match(line):
        # 보도자료·지침은 본문 문장도 □ 로 시작한다. 제목 길이를 넘으면 문단이다(d1 보도자료, 2026-11-24)
        if len(line.strip()) <= _HEADING_MAX_CHARS:
            return "HEADING", 1
        return "PARAGRAPH", None
    if _LIST_RE.match(line):
        return "LIST_ITEM", None
    # 문서가 스스로 "개요 N" 스타일로 표시한 문단은 그 수준의 제목이다(HWPX, 전체 점검 2-12).
    # 번호 패턴이 있으면 위에서 이미 정해졌고, 여기는 번호 없이 스타일만 쓴 제목을 받는다.
    # 한글에서는 개요 스타일로 본문 문장을 쓰기도 하므로 제목 길이를 넘는 문단은 제외한다.
    if layout and layout.get("heading_level") and len(line.strip()) <= _HEADING_MAX_CHARS:
        return "HEADING", int(layout["heading_level"])
    # 정규식이 아무것도 못 찾았을 때만 폰트 신호로 폴백 승격한다(문서 파싱
    # 고도화 Phase 2) — 번호/장절조 패턴 없이 굵고 큰 글씨로만 된 제목을
    # 놓치지 않기 위함. 정규식이 뭔가를 판단했다면 항상 그 판단이 우선.
    # 표지의 날짜("2025년 12월", "2025.12.21")는 굵고 크게 쓰여도 제목이 아니다(HWPX 실측, 2026-11-16)
    if _DATE_ONLY_RE.match(line.strip()) or _ADDRESSEE_RE.search(line.strip()):
        return "PARAGRAPH", None
    if layout and layout.get("is_bold") and body_font_size and layout.get("font_size"):
        if layout["font_size"] >= body_font_size + _HEADING_FONT_DELTA:
            level = 1 if layout["font_size"] >= body_font_size * _HEADING_LEVEL1_RATIO else 2
            return "HEADING", level
    return "PARAGRAPH", None


def _is_font_only_heading(line: str, layout: dict | None) -> bool:
    """번호·장절·제목 표시 없이 글자 크기와 굵기만으로 제목이 된 줄인지. _classify 의 판정 순서를 따른다."""
    numbered = _HEADING_NUMBERED_RE.match(line)
    if numbered and _plausible_numbered_heading(line, numbered.group(1)):
        return False
    if _HEADING_KOREAN_RE.match(line) or _HEADING_SQUARE_BULLET_RE.match(line):
        return False
    return not (layout and layout.get("heading_level"))


class _FontHeadingNester:
    """글꼴로만 잡힌 제목의 수준을 앞선 제목과의 글자 크기 비교로 정한다. 자기보다 글자가 큰 가장 가까운
    앞선 제목의 한 단계 아래에 두고, 최대 수준을 넘으면 최대 수준에 맞춘다(문단으로 떨어뜨리지 않음).
    번호 제목은 번호가 정한 수준을 그대로 쓰고 기준점으로만 쌓는다(HTML h2~h5 실측, 2026-11-19)."""

    def __init__(self, numbered_sizes: dict[float, int] | None = None, sizes_follow_markup: bool = False) -> None:
        self._stack: list[tuple[int, float | None]] = []
        # 글자 크기가 제목 태그에서 온 형식(HTML, 마크다운)만 크기로 번호 제목의 수준을 고친다. HWPX·PDF 의
        # 글자 크기는 단계를 그대로 반영하지 않는다(UIUX 보고서 "2. 과업 내용"이 절로 내려가는 오판, 2026-11-19)
        self._sizes_follow_markup = sizes_follow_markup
        # 장 번호 제목의 글자 크기 → 수준 1. 번호 없는 같은 크기 제목도 장 수준으로 둔다
        self._numbered_sizes = numbered_sizes or {}

    def place(self, level: int | None, layout: dict | None, font_only: bool, max_level: int | None) -> int | None:
        size = layout.get("font_size") if layout else None
        chapter_sizes = [s for s, chapter_level in self._numbered_sizes.items() if chapter_level == 1]
        if self._sizes_follow_markup and level == 1 and size is not None and chapter_sizes and size < min(chapter_sizes):
            # 번호 규칙상 수준 1("1. … 알림")이어도 장 제목보다 글자가 작으면 절 안의 목록형 번호다
            font_only = True
        if font_only and size is not None and level is not None:
            level = self._numbered_sizes.get(size) or self._level_below_larger(size)
            if max_level is not None:
                level = min(level, max_level)
        if level is None:
            return level
        return self._push(level, size)

    def _level_below_larger(self, size: float) -> int:
        """같은 크기의 가장 가까운 앞선 제목이 있으면 그 형제, 더 큰 제목이 먼저 나오면 그 한 단계 아래."""
        for stacked_level, stacked_size in reversed(self._stack):
            if stacked_size is None:
                # 글꼴 정보를 못 짝지은 번호 제목은 크기를 비교할 수 없어 기준으로 쓰지 않는다
                continue
            if stacked_size > size:
                return stacked_level + 1
            if stacked_size == size:
                return stacked_level
        return 1

    def _push(self, level: int, size: float | None) -> int:
        while self._stack and self._stack[-1][0] >= level:
            self._stack.pop()
        self._stack.append((level, size))
        return level


def _numbered_heading_sizes(text: str, layout_entries: list[dict] | None) -> dict[float, int]:
    """장 번호 제목("1 사업 개요")이 쓰는 글자 크기를 수준 1로 고정한다. 같은 크기의 번호 없는 제목("완료 결과
    요약")이 문서 제목(h1) 뒤에 먼저 나와도 장과 같은 수준을 주려고 본문 전체를 먼저 훑는다. 더 작은 크기의
    "1. …"은 절 안의 목록형 번호일 수 있어 기준으로 쓰지 않는다(고도화보고서 7.3절 알림 목록 실측)."""
    levels_by_size: dict[float, set[int]] = {}
    cursor = _LineLayoutCursor(layout_entries or [])
    for line in text.split("\n"):
        stripped = line.strip()
        layout = cursor.match(stripped) if stripped else None
        if not (layout and layout.get("is_bold") and layout.get("font_size")):
            continue
        numbered = _HEADING_NUMBERED_RE.match(stripped)
        if not numbered or not _plausible_numbered_heading(stripped, numbered.group(1)):
            continue
        if stripped[len(numbered.group(1)):].startswith(")"):
            continue
        levels_by_size.setdefault(layout["font_size"], set()).add(_number_depth(numbered.group(1)))
    if not levels_by_size:
        return {}
    # 장 번호("1 사업 개요")가 쓰는 가장 큰 크기만 기준으로 쓴다. 더 작은 크기의 "1. …"은 절 안의 목록형 번호일 수 있다
    chapter_size = max(levels_by_size)
    return {chapter_size: 1} if levels_by_size[chapter_size] == {1} else {}


_MARKUP_HEADING_SUFFIXES = (".html", ".htm", ".md", ".markdown")


def _uses_markup_headings(filename: str | None) -> bool:
    return (filename or "").lower().endswith(_MARKUP_HEADING_SUFFIXES)


def _build_blocks(
    text: str,
    layout_entries: list[dict] | None = None,
    toc_offsets: set[int] | None = None,
    page_map: list | None = None,
    max_level: int | None = None,
    markup_headings: bool = False,
) -> list[tuple[str, int | None, int, int, str, dict | None]]:
    """`markup_headings`는 제목을 태그로 표시하는 형식(HTML, 마크다운)이다. 그 형식에서 본문 글씨로 쓴 번호 줄은
    제목이 아니다.

    줄 단위로 훑어 (node_type, level, span_start, span_end, block_text,
    layout) 튜플 목록을 만든다. HEADING/LIST_ITEM/TABLE(마커)/FOOTNOTE/TOC
    줄은 각각 새 블록을 열고, 연속된 본문 줄은 현재 열린 블록(PARAGRAPH 또는
    TABLE)에 그대로 이어붙인다. 빈 줄을 만나면 진행 중인 블록이 닫힌다.
    `layout`은 병합되지 않는 단일 줄 노드(HEADING/LIST_ITEM/FOOTNOTE/TOC)에만
    채워지고, 여러 줄이 합쳐지는 PARAGRAPH/TABLE 블록은 대표 스타일이 의미가
    없어 항상 None이다."""
    blocks: list[tuple[str, int | None, int, int, str, dict | None]] = []
    offset = 0
    buf_type: str | None = None
    buf_start: int | None = None
    buf_end: int | None = None
    buf_lines: list[str] = []
    toc_offsets = toc_offsets or set()
    body_font_size = _body_font_size(layout_entries) if layout_entries else None
    cursor = _LineLayoutCursor(layout_entries or [])
    header_offsets = _running_header_offsets(text, page_map)
    # 마지막 제목 상자의 수준. 그 뒤의 줄 제목은 이만큼 아래로 내린다(title_box.py)
    box_shift = 0
    # 번호·붙임 표시가 든 제목 상자를 이미 만났는지. 그 뒤의 번호 없는 표어 상자는 제목으로 올리지 않는다
    marked_box_seen = False
    nester =_FontHeadingNester(_numbered_heading_sizes(text, layout_entries), sizes_follow_markup=markup_headings)

    def flush() -> None:
        nonlocal buf_type, buf_start, buf_end, buf_lines, box_shift
        nonlocal marked_box_seen
        box = None
        if buf_type == "TABLE":
            marked = title_box_heading(buf_lines, _HEADING_MAX_CHARS, allow_slogan=False)
            marked_box_seen = marked_box_seen or marked is not None
            box = marked or title_box_heading(buf_lines, _HEADING_MAX_CHARS, allow_slogan=not marked_box_seen)
        if box:
            blocks.append(("HEADING", box[1], buf_start, buf_end, box[0], None))
            box_shift = box[1]
        elif buf_lines:
            blocks.append((buf_type, None, buf_start, buf_end, "\n".join(buf_lines), None))
        buf_type, buf_start, buf_end, buf_lines = None, None, None, []

    for line in text.split("\n"):
        line_start = offset
        line_end = offset + len(line)
        offset = line_end + 1  # split()이 삼킨 '\n' 만큼 보정

        if not line.strip():
            flush()
            continue

        if buf_type == "TABLE":
            # 표 블록 안에서는 줄을 재분류하지 않는다 — 표의 행("1 | 2 | 3"
            # 같은)이 첫 칸이 숫자라는 이유만으로 우연히 제목 패턴과 일치해도
            # 표가 중간에 끊기면 안 된다. pdf_adapter가 표 블록을 이웃 블록과
            # 항상 빈 줄("\n\n")로만 구분해 두므로, 표는 빈 줄에서만 끝난다고
            # 안전하게 가정할 수 있다.
            buf_lines.append(line)
            buf_end = line_end
            continue

        layout = cursor.match(line.strip())

        if line_start in toc_offsets:
            # 목차로 확정된 줄은 정규식이 뭐라고 판단했든(번호 매김 때문에
            # HEADING처럼 보일 수 있음) 덮어써 가짜 제목이 트리에 섞이지
            # 않게 한다.
            flush()
            blocks.append(("TOC", None, line_start, line_end, line, layout))
            continue

        if line_start in header_offsets:
            flush()
            blocks.append(("HEADER", None, line_start, line_end, line, layout))
            continue

        node_type, level = _classify(line, layout, body_font_size)
        if box_shift and starts_with_roman(line) and len(line.strip()) <= _HEADING_MAX_CHARS:
            # 제목 상자를 쓰는 문서에서 로마 숫자로 시작하는 짧은 줄은 장 제목이다. 굵기 신호가 없어도 받는다
            if node_type in ("HEADING", "PARAGRAPH"):
                flush()
                node_type, level, box_shift = "HEADING", 1, 0
        elif node_type == "HEADING" and box_shift:
            level = shifted_level(level, box_shift, max_level)
        if node_type == "HEADING" and markup_headings and layout and not layout.get("is_bold") and (
            _HEADING_NUMBERED_RE.match(line)
        ):
            # 태그 없는 번호 줄은 제목이 아니다. 마크다운 번호 목록("1. 항목")은 목록 항목으로 둔다
            node_type, level = ("LIST_ITEM", None) if _LIST_RE.match(line) else ("PARAGRAPH", None)
        if node_type == "HEADING":
            level = nester.place(level, layout, _is_font_only_heading(line, layout), max_level)
        if node_type in ("HEADING", "LIST_ITEM", "TABLE", "FOOTNOTE"):
            flush()
            if node_type == "TABLE":
                buf_type, buf_start, buf_end, buf_lines = "TABLE", line_start, line_end, [line]
            else:
                blocks.append((node_type, level, line_start, line_end, line, layout))
            continue

        if buf_type is None:
            buf_type = "PARAGRAPH"
            buf_start = line_start
        buf_lines.append(line)
        buf_end = line_end

    flush()
    return blocks


# Document.elements(Docling 경로)가 있을 때 아래 타입 매핑으로 DocumentNode를
# 직접 구성한다. _classify()의 정규식 재분류를 전혀 거치지 않으므로, "목차가
# 제목/문단으로 오분류"되는 문제의 원인 자체(정규식이 목차 줄을 번호매김
# 패턴으로 오인)가 이 경로에서는 애초에 발생하지 않는다 — Docling이 목차를
# 별도 네이티브 타입(document_index)으로 이미 분리해 주므로 그걸 그대로
# TOC로 옮기면 된다.
_ELEMENT_TOC_TYPES = {"document_index"}
_ELEMENT_HEADING_TYPES = {"title", "section_header", "section-header"}
_ELEMENT_TABLE_TYPES = {"table"}
_ELEMENT_LIST_TYPES = {"list_item", "list-item"}
_ELEMENT_PICTURE_TYPES = {"picture", "figure"}
_ELEMENT_CAPTION_TYPES = {"caption"}
_ELEMENT_FOOTNOTE_TYPES = {"footnote"}
_ELEMENT_HEADER_TYPES = {"page_header", "page-header"}
_ELEMENT_FOOTER_TYPES = {"page_footer", "page-footer"}
# node_type에 도달했지만 본문이 비어 있으면 만들지 않는 타입들 — TABLE/IMAGE/
# TOC는 비어 있어도(TOC는 Phase 1에서 발견한 실제 갭 — document_index 요소의
# content가 현재 항상 빈 문자열) 구조상 반드시 노드가 남아야 한다.
_ELEMENT_SKIP_IF_EMPTY_TYPES = {
    "PARAGRAPH", "HEADING", "LIST_ITEM", "CAPTION", "FOOTNOTE", "HEADER", "FOOTER",
}


def _node_type_for_element(el_type: str) -> str:
    if el_type in _ELEMENT_TOC_TYPES:
        return "TOC"
    if el_type in _ELEMENT_HEADING_TYPES:
        return "HEADING"
    if el_type in _ELEMENT_TABLE_TYPES:
        return "TABLE"
    if el_type in _ELEMENT_LIST_TYPES:
        return "LIST_ITEM"
    if el_type in _ELEMENT_PICTURE_TYPES:
        return "IMAGE"
    if el_type in _ELEMENT_CAPTION_TYPES:
        return "CAPTION"
    if el_type in _ELEMENT_FOOTNOTE_TYPES:
        return "FOOTNOTE"
    if el_type in _ELEMENT_HEADER_TYPES:
        return "HEADER"
    if el_type in _ELEMENT_FOOTER_TYPES:
        return "FOOTER"
    return "PARAGRAPH"


def _original_heading_font_sizes(doc) -> dict[str, float]:
    """PDF 원본 텍스트 레이어에서 제목 요소의 실제 글자 크기를 읽는다. PDF 가 아니거나 못 읽으면 빈 사전이다."""
    if "pdf" not in (getattr(doc, "mime_type", "") or "").lower():
        return {}
    from app.core.config import settings
    from app.pipeline.blocks.pdf_heading_fonts import heading_font_sizes
    from app.services.storage import storage_service

    try:
        raw = storage_service.download_file(settings.minio_bucket_originals, doc.minio_key)
    except Exception:
        logger.warning("structure_analyze: failed to download original PDF for %s", doc.id, exc_info=True)
        return {}
    return heading_font_sizes(raw, doc.elements)


def _build_blocks_from_elements(
    elements: list[dict],
) -> list[tuple[str, int | None, int | None, int | None, str, dict | None]]:
    """`_build_blocks()`를 Docling 경로에서 대체한다. 물리적 줄 단위로 훑어
    합치는 legacy 경로와 달리, Docling의 각 요소는 이미 하나의 의미 단위
    (한 문단/한 표/한 목록 항목)이므로 여러 요소를 하나의 노드로 병합하지
    않는다 — 요소 하나가 곧 노드 하나. `layout`은 항상 채워지며(legacy 경로와
    달리 병합이 없어 대표값이 항상 의미 있음), page_number 외에 이 요소의
    원본 id도 "element_id" 키로 실어 보낸다 — TABLE 노드의 source_table_id를
    "[표 N]" 마커 파싱 없이 바로 연결하기 위함(run()에서 사용)."""
    blocks: list[tuple[str, int | None, int | None, int | None, str, dict | None]] = []
    for el in elements:
        node_type = _node_type_for_element(el.get("type", ""))
        text = (el.get("content") or {}).get("text") or ""
        if node_type in _ELEMENT_SKIP_IF_EMPTY_TYPES and not text.strip():
            continue

        level = None
        if node_type == "HEADING":
            level = (el.get("metadata") or {}).get("level") or 1

        layout = {
            "page_number": el.get("page"),
            "font_size": None,
            "is_bold": node_type == "HEADING",
            "is_italic": False,
            "element_id": el.get("id"),
        }
        blocks.append((node_type, level, el.get("span_start"), el.get("span_end"), text, layout))
    return blocks


def _page_map_for_text(doc, text: str) -> list | None:
    """page_map은 원문(parsed_text) 위치 기준이다. 구조 분석이 받은 텍스트가 원문과 다르면 쪽 끝 위치를 옮긴다."""
    page_map = getattr(doc, "page_map", None)
    parsed = getattr(doc, "parsed_text", None)
    if not page_map or not parsed or parsed == text:
        return page_map
    from app.pipeline.page_alignment import OffsetMapper

    mapper = OffsetMapper(parsed, text)
    return [[mapper.map(end), page] for end, page in page_map]


def _node_page_locator(doc, text: str):
    """요소에 쪽 정보가 없는 경로(HWP/HWPX, 스캔 PDF OCR, legacy PDF)의 노드 쪽 번호를 page_map으로 찾는다.
    예전에는 이 경로의 노드가 모두 쪽 번호 없이 저장돼 원문 대조가 되지 않았다(2026-11-16).
    page_map 항목이 하나뿐이면(DOCX처럼 쪽을 모르는 형식) 모두 1쪽으로 보여 오해를 사므로 쓰지 않는다."""
    page_map = getattr(doc, "page_map", None)
    if not page_map or len(page_map) < 2:
        return None
    from app.pipeline.page_alignment import PageLocator

    return PageLocator(getattr(doc, "parsed_text", None) or text, page_map, text)


def _extract_title(
    built_blocks: list[tuple[str, int | None, int | None, int | None, str, dict | None]],
) -> str | None:
    """트리의 첫 HEADING 블록 텍스트를 문서 제목으로 삼는다 — legacy/elements
    두 경로 모두 `_build_blocks*()`가 만드는 동일한 6-tuple shape를 그대로
    받으므로 경로 분기가 필요 없다. 헤딩이 하나도 없으면 None(프론트가
    original_filename로 폴백 표시)."""
    for node_type, _level, _start, _end, block_text, _layout in built_blocks:
        if node_type == "HEADING" and block_text.strip():
            return block_text.strip()[:500]
    return None


_HEADING_STYLE_PREFIXES = ("title", "section_header", "section-header", "heading")


def _title_lead_lines(doc, built_blocks) -> list[LeadLine]:
    """제목 판정이 볼 앞쪽 줄 — 1쪽 레이아웃(글자 크기·제목 표시)이 있으면 그것을, 없으면(HWPX 등)
    트리의 앞쪽 블록 텍스트를 쓴다. 장 번호가 붙은 heading("1. 사업개요")은 제목 표시를 달지 않는다."""
    layout = [
        entry for entry in (doc.extraction_layout or [])
        if entry.get("page_number") == 1 and entry.get("role") not in ("header", "footer") and entry.get("text")
    ]
    if len(layout) >= 2:
        return [
            LeadLine(
                text=entry["text"], size=entry.get("font_size"),
                is_heading=str(entry.get("style_name") or "").lower().startswith(_HEADING_STYLE_PREFIXES),
            )
            for entry in layout
        ]
    lines: list[LeadLine] = []
    for node_type, _level, _start, _end, block_text, _layout in built_blocks[:12]:
        if node_type in ("TABLE", "TOC"):
            continue
        is_heading = node_type == "HEADING" and not _is_chapter_heading(block_text)
        lines.extend(
            LeadLine(text=line, is_heading=is_heading) for line in block_text.splitlines() if line.strip()
        )
    return lines


def _apply_document_title(doc, built_blocks) -> None:
    """Document.title 을 판정해 채운다. 사용자가 직접 고친 제목(user_edited_fields)은 덮어쓰지 않는다."""
    if "title" in (getattr(doc, "user_edited_fields", None) or []):
        return
    doc.title = resolve_title(
        _title_lead_lines(doc, built_blocks),
        filename=getattr(doc, "original_filename", None) or getattr(doc, "filename", None) or "",
        embedded_title=getattr(doc, "source_title", None),
        ocr_used=bool(getattr(doc, "ocr_used", False)),
        fallback_heading=_extract_title(built_blocks),
    )


def _apply_document_type(db, doc, built_blocks: list) -> list:
    """문서 유형을 정해 판별값을 문서에 남기고, 규정이면 조문 구조를 입힌 블록 목록을 돌려준다.

    유형은 사용자가 지정한 값(문서, 컬렉션 기본값)을 먼저 쓴다. 판별값은 지정값이 있어도 기록해 화면에서
    "자동 판별: 규정·법령"처럼 보여 줄 수 있게 한다(services/document_type.py)."""
    from app.services.document_type import GENERAL, REGULATION, chosen_document_type, collection_default_type

    texts = [block[4] for block in built_blocks if block[0] != "TOC"]
    doc.detected_document_type = REGULATION if looks_like_regulation(texts) else GENERAL
    chosen = chosen_document_type(getattr(doc, "document_type", None), collection_default_type(db, doc))
    if (chosen or doc.detected_document_type) != REGULATION:
        return built_blocks
    return apply_legal_structure(built_blocks)


class StructureAnalyzeConfig(BaseModel):
    detect_headings: bool = True
    # 2026-11-20 3 → 5. 글자 크기로 나누는 무리는 그대로 셋이고, 4·5단계는 점 번호·기호 순서와 HWP 개요 수준으로 정한다
    heading_max_level: int = 5
    detect_lists: bool = True
    # 문서 파싱 고도화 Phase 2 — 이제 실질 동작(이전엔 no-op).
    detect_toc: bool = True
    use_font_signals: bool = True
    preserve_clause_number: bool = True


class StructureAnalyzeBlock(BaseBlock):
    @property
    def block_type(self) -> str:
        return "structure_analyze"

    @property
    def block_version(self) -> str:
        # Bumped: extraction_layout(있으면) 기반 폰트 신호/목차/각주 분류에
        # 이어, TABLE 노드에 source_table_id도 이제 채운다(문서 파싱 고도화
        # Phase 3) — 캐시된 이전 결과를 재생하면 안 된다.
        #
        # 1.3.0: Document.elements(Docling 경로)가 있으면 _classify() 정규식
        # 경로를 완전히 건너뛰고 _build_blocks_from_elements()로 직접 트리를
        # 구성한다 — 목차(document_index)가 이제 TOC로 바로 매핑되어 제목/
        # 문단으로 오분류되던 문제가 이 경로에서는 발생하지 않는다(Docling
        # 도입 설계서, 2026-07-23 Phase 2). elements가 없는 문서는 기존 경로
        # 그대로.
        #
        # 1.4.0: 트리 구성 후 첫 HEADING 노드의 텍스트를 Document.title로
        # 스탬프한다 — 캐시된 이전 결과는 title을 채우지 않았으므로 재생하면
        # 안 된다(메타 정보 생성 설계서, 2026-07-23 Phase 1).
        #
        # 1.5.0: DocumentNode.element_id를 이제 영속화한다(elements 경로만) —
        # chunk_strategies.py(Phase 4)가 이 값으로 DocumentChunk.element_id를
        # 채운다. 캐시된 이전 결과는 이 컬럼이 항상 None이었다.
        #
        # 1.6.0: DocumentNode.style에 style_name/font_name도 채운다(legacy
        # 경로만, extraction_layout에서 전달) — 캐시된 이전 결과는 이 두
        # 키가 없었다(메타 정보 생성.txt 2절, 2026-07-24).
        #
        # 1.7.0: Document.title 을 "첫 HEADING"이 아니라 title_resolver(내장 제목·표지 줄·글자 크기·
        # 파일명)로 정하고, 사용자가 고친 제목(user_edited_fields)은 덮어쓰지 않는다 — 캐시된 이전
        # 결과는 표지 연도·장 제목이 제목이 된 값이다.
        #
        # 1.11.0: Docling 경로의 제목 레벨을 bbox 글자 크기로 다시 정하고, 목차 쪽 제목은 TOC로, 쪽 가장자리
        # 반복 문구는 HEADER/FOOTER로 바꾸며, 한 글자 문단은 버린다(structure_refine.py, 2026-11-13).
        #
        # 1.12.0: 목차 쪽의 문단과 목록 항목도 다른 쪽 제목과 같으면 TOC로 바꾼다(2026-11-13).
        #
        # 1.13.0: 요소에 쪽 정보가 없는 경로의 노드 쪽 번호를 page_map으로 채운다(2026-11-16).
        # 같은 날 legacy 경로의 번호 제목 판정을 좁히고(_plausible_numbered_heading), 여러 번 반복되는 짧은 줄을
        # 쪽 가장자리에서 여러 쪽에 반복되는 짧은 줄을 머리말(HEADER)로 표시한다(_running_header_offsets).
        #
        # 1.15.0: 번호로 시작하는 한 줄짜리 표(제목 상자)를 제목으로 올리고 그 아래 줄 제목의 수준을 내린다
        # (title_box.py). 글자를 한 자씩 띄운 번호 제목("1. 목    적")도 제목으로 받는다(2026-11-17).
        # 1.16.0: "목차"/"차례" 제목 뒤 항목이 본문에 다시 나오면 쪽 번호가 없어도 목차로 본다.
        # 가운뎃점 리더("······ 3")도 목차 줄로 받는다(toc_detection.py, 2026-11-17).
        # 1.17.0: 여러 줄을 담은 글꼴 항목을 줄마다 나눠 짝짓는다. HTML 문서 뒤쪽의 큰 제목(번호 없는
        # "부록 A. 용어" 등)이 글꼴 정보를 잃고 문단이 되던 문제. 번호 없이 글꼴로만 잡힌 제목은 모두 수준 1이던
        # 것을, 앞선 더 큰 제목의 한 단계 아래(같은 크기면 형제)에 두어 번호 제목 아래로 들어가게 한다(2026-11-19).
        # 1.18.0: Docling PDF 제목의 글자 크기를 원본 텍스트 레이어에서 읽고(pdf_heading_fonts.py), 같은 크기면
        # 제목 기호 순서(1. > □ > ○ > -)로 단계를 나눈다. "1. 사업 개요" 아래 "□ 사업 개요"가 장 제목보다 높은
        # 단계로 잡혀 청크 절 경로에서 장 제목이 빠지던 문제(2026-11-20).
        # 1.18.1: "6." 다음 "7."처럼 번호가 이어지고 크기가 8% 안이면 같은 단계로 맞춘다(자율형공장 공고문 7장).
        # 1.19.0: 점 번호 깊이("3." < "3.2" < "3.2.1")로 단계를 나눈다. 번호의 부모-자식 관계가 이어지는 제목에만
        # 적용하고, 하위 절이 없는 장은 앞뒤 장과 번호가 이어지면 같은 단계로 둔다. "해설 N"·"부록 N" 같은 묶음 제목은
        # 그 아래 번호 장보다 한 단계 위에 둔다(KRS SG, KR S-03010 등 규격 문서, 2026-11-20).
        # 1.20.0: 제목 단계 상한을 3에서 5로 올린다. 글자 크기 무리는 셋까지만 나누고, "1.1.2"처럼 네 겹 이상인
        # 번호와 하위 기호 제목만 4·5단계로 내린다(KR S-03010 해설 아래 1.1.2, 2026-11-20).
        # 1.21.0: 같은 크기의 "1." 아래 "가.", 그 아래 "(1)"·"1)" 제목을 한 단계씩 내린다(세원화성 에너지진단보고서).
        #         "○○○ 귀하" 같은 수신인 줄은 제목으로 보지 않는다(제안요청서, 2026-11-20 감사).
        #         쪽 가장자리 줄을 셀 때 표 줄을 빼서, 표가 뒤에 붙은 쪽의 꼬리말도 머리말·꼬리말로 잡는다.
        # 1.22.0: Docling 이 일반 글로 읽은 장 구분 쪽의 "PART 01"과 같은 쪽 바로 뒤의 장 이름을 1단계 제목 하나로
        #         합친다(경기도 데이터분석 사례집, 2026-11-20 감사).
        # 1.23.0: 제목 길이(50자)를 넘는 □ 줄은 본문 문장이므로 문단으로 둔다. 붙임·참고 표시 상자("참고1 | 법령체계
        #         개편(안)")와 번호 없는 표어 상자(" | 제명을 바꾼다! (…)")도 제목 상자로 읽는다(title_box.py, 2026-11-24).
        # 1.23.1: 번호·붙임 제목 상자를 이미 쓴 문서에서는 표어 상자를 제목으로 올리지 않는다. 조사료 지침의 주체 표시
        #         상자("시·도(시·군), 농협경제지주…")가 1단계 제목이 되어 장 밖으로 튀어나왔다(2026-11-24).
        # 1.24.0: 붙임표 번호 절 제목("1-1. 개발 범위")을 점 번호처럼 제목으로 받는다(AIDE 제안서 DOCX, 2026-11-25).
        # 1.25.0: 파서가 목록 항목으로 읽은 줄(Docling list_item)은 번호가 붙어도 목록 항목으로 둔다. 목록 기호를 본문에
        #         되살리면서 "1. 데이터 파이프라인" 같은 짧은 항목이 제목이 되지 않게 했다(2026-11-26).
        # 1.26.0: 줄 전체가 "목차"/"차례"인 제목은 목차(TOC) 노드로 둔다. 본문이 "목 차" 아래로 들어가 검색 결과의
        #         절 경로가 "목 차 > …"로 보였다(행정·공공기관 예방점검 가이드 청크 313개, 2026-11-27).
        # 1.27.0: 문서 유형을 정해 detected_document_type 을 기록하고, 규정·법령이면 편·장·절·관·조 번호 체계로 제목 단계를
        #         다시 매기며 "제1조(목적) 본문"을 조 제목과 본문으로 나눈다(legal_structure.py, 2026-11-27).
        return "1.27.0"

    @property
    def category(self) -> str:
        return "구조·보호"

    @property
    def config_schema(self):
        return StructureAnalyzeConfig

    def run(self, context: BlockContext) -> BlockResult:
        from app.db.models.document import Document
        from app.db.models.document_node import DocumentNode
        from app.db.session import get_sync_db

        if not context.document_id:
            raise ValueError("실행할 문서가 지정되지 않았습니다.")
        cfg = StructureAnalyzeConfig(**(context.config or {}))
        text = _upstream_text(context)

        db = get_sync_db()
        try:
            doc = db.get(Document, context.document_id)
            if doc is None:
                raise ValueError("지정된 문서를 찾을 수 없습니다.")

            # 헤더/꼬리말(role)은 이미 parsed_text 조립 단계에서 제외됐으므로
            # extraction_layout에는 남아있어도 여기서는 무시 — 표는 텍스트에
            # "[표 N]" 마커로만 남고 line_layout에는 애초에 없다(어댑터가 표
            # bbox를 제외하고 계산하므로).
            layout_entries = None
            if cfg.use_font_signals and doc.extraction_layout:
                layout_entries = [
                    line for line in doc.extraction_layout
                    if line.get("role") not in ("header", "footer")
                ]
            toc_offsets = _detect_toc_line_offsets(text) if cfg.detect_toc else set()

            # 이 문서의 이전 run이 만든 트리는 재처리 시 대체 — chunk_split의
            # 기존 재생성 패턴과 동일한 이유(중복 방지).
            db.query(DocumentNode).filter(DocumentNode.document_id == doc.id).delete()

            root_id = str(uuid.uuid4())
            db.add(DocumentNode(
                id=root_id, document_id=doc.id, run_id=context.run_id, node_type="DOCUMENT",
                level=0, sort_order=0, parent_node_id=None,
                span_start=0, span_end=len(text),
            ))

            sort_order = 1
            stack: list[tuple[int, str]] = [(0, root_id)]
            node_count = 1

            # Docling 도입 설계서(2026-07-23) Phase 2 — Document.elements가
            # 있으면(engine=="docling"로 처리된 PDF) 그것을 직접 소비하고,
            # 없으면(HWP/HWPX, 또는 legacy 엔진) 기존 정규식 경로로 완전히
            # 폴백한다 — 회귀 없음.
            built_blocks = (
                refine_element_blocks(
                    _build_blocks_from_elements(doc.elements), doc.elements, cfg.heading_max_level,
                    font_sizes=_original_heading_font_sizes(doc),
                )
                if doc.elements
                else _build_blocks(
                    text, layout_entries, toc_offsets, _page_map_for_text(doc, text), cfg.heading_max_level,
                    markup_headings=_uses_markup_headings(getattr(doc, "original_filename", None)),
                )
            )
            built_blocks = _apply_document_type(db, doc, built_blocks)

            page_locator = _node_page_locator(doc, text)
            for node_type, level, span_start, span_end, block_text, layout in built_blocks:
                if node_type == "HEADING" and not cfg.detect_headings:
                    node_type, level = "PARAGRAPH", None
                if node_type == "LIST_ITEM" and not cfg.detect_lists:
                    node_type, level = "PARAGRAPH", None
                if node_type == "TOC" and not cfg.detect_toc:
                    # elements 경로는 document_index를 항상 TOC로 매핑하므로
                    # (legacy 경로의 toc_offsets 계산과 달리 조건 없음), 여기서
                    # 사용자가 끈 detect_toc 설정을 동일하게 반영한다.
                    node_type = "PARAGRAPH"
                if node_type == "HEADING" and level is not None and level > cfg.heading_max_level:
                    # 설정된 최대 레벨을 넘는 번호 매김은 제목이 아니라 본문
                    # 취급(예: 조항 번호를 제목으로 오인하지 않도록).
                    node_type, level = "PARAGRAPH", None
                if node_type == "HEADING" and is_toc_title(block_text):
                    # "목 차" 제목 줄은 목차 영역의 머리다. 제목으로 두면 뒤에 1단계 제목이 다시 나오지 않는 문서에서
                    # 본문 전체가 "목차" 아래로 들어가, 청크 313개의 절 경로가 "목 차 > …"였다(예방점검 가이드, 2026-11-27)
                    node_type, level = ("TOC", None) if cfg.detect_toc else ("PARAGRAPH", None)

                if node_type == "HEADING":
                    while len(stack) > 1 and stack[-1][0] >= level:
                        stack.pop()
                    parent_id = stack[-1][1]
                else:
                    parent_id = stack[-1][1]

                node_id = str(uuid.uuid4())
                style = None
                if layout:
                    style = {
                        "font_size": layout.get("font_size"),
                        "is_bold": layout.get("is_bold"),
                        "is_italic": layout.get("is_italic"),
                        # 메타 정보 생성.txt 2절 style/font_name — legacy(비-Docling)
                        # 경로는 extraction_layout에서 실제 값을 전달받지만(docx의
                        # style_name, docx/pdf의 font_name), elements(Docling) 경로는
                        # _build_blocks_from_elements()가 layout에 이 키를 아예 넣지
                        # 않아 항상 None — Docling 라이브러리가 폰트 정보를 노출하지
                        # 않는 알려진 제약(자동 생성 불가, PATCH로 수동 입력).
                        "style_name": layout.get("style_name"),
                        "font_name": layout.get("font_name"),
                    }
                source_table_id = None
                if node_type == "TABLE":
                    # elements 경로는 요소 자기 id가 곧 RawTableCandidate.id라
                    # "[표 N]" 마커를 파싱할 필요가 없다(Docling 도입 설계서
                    # Phase 2) — legacy 경로만 마커 파싱으로 폴백.
                    element_id = layout.get("element_id") if layout else None
                    source_table_id = element_id or _resolve_source_table_id(block_text, doc.tables)
                db.add(DocumentNode(
                    id=node_id, document_id=doc.id, run_id=context.run_id, node_type=node_type,
                    level=level, sort_order=sort_order, parent_node_id=parent_id,
                    span_start=span_start, span_end=span_end,
                    text=block_text[:2000],
                    page_number=(layout or {}).get("page_number") or (
                        page_locator.page_for(span_start) if page_locator and span_start is not None else None
                    ),
                    style=style,
                    source_table_id=source_table_id,
                    # 메타 정보 생성 설계서(2026-07-23) Phase 4 — chunk_strategies.py가
                    # DocumentChunk.element_id를 스탬프할 때 여기서 읽어간다.
                    # legacy 경로(layout 없음/element_id 없음)는 항상 None.
                    element_id=layout.get("element_id") if layout else None,
                ))
                sort_order += 1
                node_count += 1
                if node_type == "HEADING":
                    stack.append((level, node_id))

            _apply_document_title(doc, built_blocks)

            db.commit()

            return BlockResult(
                output={**_carry(context), "text": text, "node_count": node_count},
                metrics={"node_count": node_count},
            )
        finally:
            db.close()
