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
import re
import uuid

from pydantic import BaseModel

from app.pipeline.blocks.base import BaseBlock, BlockContext, BlockResult
from app.pipeline.blocks.content_blocks import _carry, _upstream_text

_HEADING_NUMBERED_RE = re.compile(r"^(\d+(?:\.\d+)*)[.\)]?\s+\S")
_HEADING_KOREAN_RE = re.compile(r"^제\s*\d+\s*[장절조편]")
_LIST_RE = re.compile(r"^([-*•]|\d+[\).])\s+\S")
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
_TOC_ENTRY_RE = re.compile(r".{2,}[.…\s]{3,}\d{1,4}\s*$")
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


class _LineLayoutCursor:
    """text.split("\n")로 훑는 줄과 extraction_layout 항목을 순차 정렬한다
    (완전한 문자 오프셋 대조 대신, 작은 lookahead 창 안에서 텍스트가 일치하는
    다음 항목을 찾는 최선 노력 방식 — 표/헤더/푸터처럼 한쪽에만 있는 줄이
    있어도 깨지지 않는다)."""

    def __init__(self, entries: list[dict]):
        self._entries = entries
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
    m = _HEADING_NUMBERED_RE.match(line)
    if m:
        level = m.group(1).count(".") + 1
        return "HEADING", level
    if _HEADING_KOREAN_RE.match(line):
        return "HEADING", 1
    if _LIST_RE.match(line):
        return "LIST_ITEM", None
    # 정규식이 아무것도 못 찾았을 때만 폰트 신호로 폴백 승격한다(문서 파싱
    # 고도화 Phase 2) — 번호/장절조 패턴 없이 굵고 큰 글씨로만 된 제목을
    # 놓치지 않기 위함. 정규식이 뭔가를 판단했다면 항상 그 판단이 우선.
    if layout and layout.get("is_bold") and body_font_size and layout.get("font_size"):
        if layout["font_size"] >= body_font_size + _HEADING_FONT_DELTA:
            level = 1 if layout["font_size"] >= body_font_size * _HEADING_LEVEL1_RATIO else 2
            return "HEADING", level
    return "PARAGRAPH", None


def _build_blocks(
    text: str,
    layout_entries: list[dict] | None = None,
    toc_offsets: set[int] | None = None,
) -> list[tuple[str, int | None, int, int, str, dict | None]]:
    """줄 단위로 훑어 (node_type, level, span_start, span_end, block_text,
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

    def flush() -> None:
        nonlocal buf_type, buf_start, buf_end, buf_lines
        if buf_lines:
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

        node_type, level = _classify(line, layout, body_font_size)
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


# Docling 도입 설계서(2026-07-23) Phase 2 — Document.elements(Docling 경로)가
# 있을 때 아래 타입 매핑으로 DocumentNode를 직접 구성한다. _classify()의
# 정규식 재분류를 전혀 거치지 않으므로, 사용자가 지적한 "목차가 제목/문단으로
# 오분류" 문제의 원인 자체(정규식이 목차 줄을 번호매김 패턴으로 오인)가 이
# 경로에서는 애초에 발생하지 않는다 — Docling이 목차를 별도 네이티브 타입
# (document_index)으로 이미 분리해 주므로 그걸 그대로 TOC로 옮기면 된다.
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


def _extract_title(
    built_blocks: list[tuple[str, int | None, int | None, int | None, str, dict | None]],
) -> str | None:
    """트리의 첫 HEADING 블록 텍스트를 문서 제목으로 삼는다(메타 정보 생성
    설계서, 2026-07-23 Phase 1) — legacy/elements 두 경로 모두
    `_build_blocks*()`가 만드는 동일한 6-tuple shape를 그대로 받으므로 경로
    분기가 필요 없다. 헤딩이 하나도 없으면 None(프론트가 original_filename로
    폴백 표시)."""
    for node_type, _level, _start, _end, block_text, _layout in built_blocks:
        if node_type == "HEADING" and block_text.strip():
            return block_text.strip()[:500]
    return None


class StructureAnalyzeConfig(BaseModel):
    detect_headings: bool = True
    heading_max_level: int = 3
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
        return "1.6.0"

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
                _build_blocks_from_elements(doc.elements)
                if doc.elements
                else _build_blocks(text, layout_entries, toc_offsets)
            )

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
                    page_number=layout.get("page_number") if layout else None,
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

            doc.title = _extract_title(built_blocks)

            db.commit()

            return BlockResult(
                output={**_carry(context), "text": text, "node_count": node_count},
                metrics={"node_count": node_count},
            )
        finally:
            db.close()
