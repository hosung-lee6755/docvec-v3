"""구조 분석 블록: 문서 구조 트리 — 통합 설계서 §3.3⑤.

어댑터(app/pipeline/adapters/*)가 글꼴 크기/굵기 같은 스타일 신호를 전혀
노출하지 않으므로(RawTextBlock은 block_type/bbox만 가짐), 이 블록은 순수
텍스트 휴리스틱(번호/기호 패턴 + 줄 단위 분류)만으로 트리를 만든다.
`use_font_signals`/`detect_toc` 설정은 받되 현재는 no-op — 어댑터가 스타일
신호를 노출하게 되면 그때 실질 동작을 채운다.

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


def _classify(line: str) -> tuple[str, int | None]:
    if _TABLE_MARKER_RE.match(line):
        return "TABLE", None
    m = _HEADING_NUMBERED_RE.match(line)
    if m:
        level = m.group(1).count(".") + 1
        return "HEADING", level
    if _HEADING_KOREAN_RE.match(line):
        return "HEADING", 1
    if _LIST_RE.match(line):
        return "LIST_ITEM", None
    return "PARAGRAPH", None


def _build_blocks(text: str) -> list[tuple[str, int | None, int, int, str]]:
    """줄 단위로 훑어 (node_type, level, span_start, span_end, block_text)
    튜플 목록을 만든다. HEADING/LIST_ITEM/TABLE(마커) 줄은 각각 새 블록을
    열고, 연속된 본문 줄은 현재 열린 블록(PARAGRAPH 또는 TABLE)에 그대로
    이어붙인다. 빈 줄을 만나면 진행 중인 블록이 닫힌다."""
    blocks: list[tuple[str, int | None, int, int, str]] = []
    offset = 0
    buf_type: str | None = None  # "PARAGRAPH" 또는 "TABLE"
    buf_start: int | None = None
    buf_end: int | None = None
    buf_lines: list[str] = []

    def flush() -> None:
        nonlocal buf_type, buf_start, buf_end, buf_lines
        if buf_lines:
            blocks.append((buf_type, None, buf_start, buf_end, "\n".join(buf_lines)))
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

        node_type, level = _classify(line)
        if node_type in ("HEADING", "LIST_ITEM", "TABLE"):
            flush()
            if node_type == "TABLE":
                buf_type, buf_start, buf_end, buf_lines = "TABLE", line_start, line_end, [line]
            else:
                blocks.append((node_type, level, line_start, line_end, line))
            continue

        if buf_type is None:
            buf_type = "PARAGRAPH"
            buf_start = line_start
        buf_lines.append(line)
        buf_end = line_end

    flush()
    return blocks


class StructureAnalyzeConfig(BaseModel):
    detect_headings: bool = True
    heading_max_level: int = 3
    detect_lists: bool = True
    detect_toc: bool = False  # no-op — TOC 자동 인식은 미구현
    use_font_signals: bool = False  # no-op — 어댑터가 글꼴 신호를 노출하지 않음
    preserve_clause_number: bool = True


class StructureAnalyzeBlock(BaseBlock):
    @property
    def block_type(self) -> str:
        return "structure_analyze"

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

            for node_type, level, span_start, span_end, block_text in _build_blocks(text):
                if node_type == "HEADING" and not cfg.detect_headings:
                    node_type, level = "PARAGRAPH", None
                if node_type == "LIST_ITEM" and not cfg.detect_lists:
                    node_type, level = "PARAGRAPH", None
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
                db.add(DocumentNode(
                    id=node_id, document_id=doc.id, run_id=context.run_id, node_type=node_type,
                    level=level, sort_order=sort_order, parent_node_id=parent_id,
                    span_start=span_start, span_end=span_end,
                    text=block_text[:2000],
                ))
                sort_order += 1
                node_count += 1
                if node_type == "HEADING":
                    stack.append((level, node_id))

            db.commit()

            return BlockResult(
                output={**_carry(context), "text": text, "node_count": node_count},
                metrics={"node_count": node_count},
            )
        finally:
            db.close()
