"""PDF 표를 읽기 순서로 놓고 "[표 N]" 번호를 문서 처음부터 다시 매긴다(2026-11-27).

기존 PDF 경로(pdf_adapter)와 스캔 쪽 표 보강(scan_layout)은 번호를 따로 매겼다. 선 표는 면적 순서로, 선 없는 표는
쪽의 맨 뒤로, OCR 쪽의 표는 문서 끝 번호로 붙어 법령심사 보고서에서 위 표가 [표 3], 아래 표가 [표 2]가 되고
9쪽 표가 [표 18], 11쪽 표가 [표 4]가 되었다(표가 있는 85건 중 6건에서 쪽 사이 역전).

구조 분석은 "[표 N]"을 Document.tables 의 N 번째 표로 찾는다(structure_blocks._resolve_source_table_id).
Document.tables 는 쪽 순서, 쪽 안의 table_candidates 순서로 만들어지므로, 표 후보와 표 글 블록을 함께 옮기고
번호를 같은 순서로 다시 쓴다.
"""
import re

from app.pipeline.adapters.base import RawParsedDocument, RawTableCandidate

_MARKER_RE = re.compile(r"^\[표\s*\d+\]")
# scan_layout 의 표 좌표는 Docling 좌표(아래쪽 원점, 위 가장자리 값이 더 크다)다
_BOTTOM_ORIGIN_SOURCES = {"ocr_layout"}


def _sort_key(candidate: RawTableCandidate, index: int) -> tuple:
    """(좌표 유무, 위쪽 순서, 왼쪽, 원래 순서). 좌표가 없는 표는 원래 순서 그대로 쪽 끝에 둔다."""
    bbox = candidate.bbox
    if not bbox:
        return (1, 0.0, 0.0, index)
    top = -bbox[1] if candidate.detected_as in _BOTTOM_ORIGIN_SOURCES else bbox[1]
    return (0, round(top, 1), bbox[0], index)


def sorted_by_reading_order(candidates: list[RawTableCandidate]) -> list[RawTableCandidate]:
    """같은 쪽 표를 위에서 아래, 왼쪽에서 오른쪽 순서로."""
    order = sorted(range(len(candidates)), key=lambda i: _sort_key(candidates[i], i))
    return [candidates[i] for i in order]


def renumber_tables(parsed: RawParsedDocument) -> int:
    """쪽마다 표 후보와 표 글 블록을 읽기 순서로 놓고 번호를 1부터 다시 쓴다. 번호나 자리가 바뀐 표 수를 돌려준다.

    표 글 블록과 표 후보는 어댑터가 같은 순서로 만든다(쪽 안 k 번째 표 블록 = k 번째 표 후보). 짝이 맞지 않는
    쪽은 순서를 건드리지 않고 번호만 센다."""
    ordinal = 0
    changed = 0
    for page in sorted(parsed.pages, key=lambda p: p.page_number):
        slots = [i for i, block in enumerate(page.text_blocks) if block.block_type == "table"]
        if len(slots) != len(page.table_candidates):
            ordinal += len(slots)
            continue
        blocks = [page.text_blocks[i] for i in slots]
        order = sorted(range(len(slots)), key=lambda k: _sort_key(page.table_candidates[k], k))
        page.table_candidates = [page.table_candidates[k] for k in order]
        for position, (slot, k) in enumerate(zip(slots, order, strict=False)):
            ordinal += 1
            block = blocks[k]
            renamed = _MARKER_RE.sub(f"[표 {ordinal}]", block.text, count=1)
            if renamed != block.text or position != k:
                changed += 1
            block.text = renamed
            page.text_blocks[slot] = block
    return changed
