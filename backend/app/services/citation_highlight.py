"""인용 위치 표시(전체 점검 1-7, 2026-11-16).

답변이 인용한 청크가 원문의 어느 자리인지, 그 쪽을 그림으로 그리고 근거 영역에 색을 입혀 돌려준다.
브라우저의 PDF 보기(iframe)에는 영역을 그릴 수 없어서 서버에서 그린다.

영역은 두 가지 방법으로 찾는다.
1. Docling이 남긴 요소 좌표(Document.elements의 bbox). 청크가 나온 구조 노드의 element_id로 잇는다.
2. 좌표가 없으면(HWP, DOCX, 예전 엔진) 청크의 줄을 그 쪽의 글자 층에서 찾는다.
글자 층이 없는 스캔본은 둘 다 안 되므로 쪽만 보여 주고, 찾은 영역 수 0을 돌려준다.
"""
from dataclasses import dataclass

RENDER_DPI = 110
_FILL = (1.0, 0.85, 0.2)
_STROKE = (0.9, 0.45, 0.0)
_FILL_OPACITY = 0.3
# 글자 층에서 찾을 때 쓰는 줄의 수와 길이. 줄이 길면 줄바꿈 위치가 달라 못 찾는다
_MAX_SNIPPETS = 12
_SNIPPET_CHARS = 30
_MIN_SNIPPET_CHARS = 6
# 지정한 쪽에서 못 찾았을 때 다른 쪽을 훑는 범위
_MAX_SCAN_PAGES = 300


@dataclass(frozen=True)
class HighlightTarget:
    page_number: int
    # Docling 좌표의 상자들(같은 쪽의 것만)
    boxes: tuple[tuple[float, float, float, float], ...]
    snippets: tuple[str, ...]


def snippets_from(text: str) -> tuple[str, ...]:
    """청크 본문에서 글자 층 검색에 쓸 줄을 고른다. 표의 칸막이 줄과 너무 짧은 줄은 뺀다."""
    out = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("|") or stripped.startswith("[표 "):
            continue
        if len(stripped) < _MIN_SNIPPET_CHARS:
            continue
        out.append(stripped[:_SNIPPET_CHARS])
        if len(out) >= _MAX_SNIPPETS:
            break
    return tuple(out)


def build_target(chunk, node_element_ids: list[str], elements: list | None) -> HighlightTarget:
    """청크와 그 구조 노드, 문서 요소에서 표시할 쪽과 영역을 정한다."""
    wanted = {i for i in [getattr(chunk, "element_id", None), *node_element_ids] if i}
    matched = [
        e for e in (elements or [])
        if isinstance(e, dict) and e.get("id") in wanted and e.get("bbox") and e.get("page")
    ]
    page_number = chunk.page_start or (min(e["page"] for e in matched) if matched else 1)
    boxes = tuple(tuple(float(v) for v in e["bbox"][:4]) for e in matched if e["page"] == page_number)
    return HighlightTarget(
        page_number=page_number, boxes=boxes,
        snippets=snippets_from(chunk.original_text or chunk.chunk_text),
    )


def _to_rect(fitz, box: tuple[float, float, float, float], page_height: float):
    """Docling 상자(left, top, right, bottom)를 fitz 좌표로. 원점이 왼쪽 아래면 top이 bottom보다 크다."""
    left, top, right, bottom = box
    if top > bottom:
        top, bottom = page_height - top, page_height - bottom
    return fitz.Rect(min(left, right), min(top, bottom), max(left, right), max(top, bottom))


def _search(page, snippets: tuple[str, ...]) -> list:
    return [rect for snippet in snippets for rect in page.search_for(snippet)]


def render_highlight(pdf_bytes: bytes, target: HighlightTarget) -> tuple[bytes, int, int]:
    """(PNG, 실제로 그린 쪽 번호, 표시한 영역 수). 쪽 번호가 범위를 벗어나면 가까운 쪽으로 맞춘다."""
    import fitz

    with fitz.open(stream=pdf_bytes, filetype="pdf") as pdf:
        if pdf.page_count == 0:
            raise ValueError("빈 PDF입니다")
        page_number = max(1, min(target.page_number, pdf.page_count))
        page = pdf[page_number - 1]
        rects = [_to_rect(fitz, box, page.rect.height) for box in target.boxes]
        if not rects:
            rects = _search(page, target.snippets)
        if not rects and target.snippets:
            # DOCX와 HWP는 쪽 번호가 미리보기 PDF의 쪽과 어긋날 수 있다. 다른 쪽에서 가장 많이 맞는 쪽을 고른다
            best = max(
                ((_search(other, target.snippets), other) for other in pdf.pages(0, min(pdf.page_count, _MAX_SCAN_PAGES))),
                key=lambda found: len(found[0]),
            )
            if best[0]:
                rects, page = best
                page_number = page.number + 1
        rects = [r for r in rects if not r.is_empty and r.intersects(page.rect)]
        for rect in rects:
            page.draw_rect(rect, color=_STROKE, fill=_FILL, fill_opacity=_FILL_OPACITY, width=1.0)
        return page.get_pixmap(dpi=RENDER_DPI).tobytes("png"), page_number, len(rects)
