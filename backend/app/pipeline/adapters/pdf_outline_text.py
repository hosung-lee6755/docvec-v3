"""글자를 윤곽선(벡터 도형)으로 그린 PDF 쪽 찾기.

PPT 를 PDF 로 내보내면서 글꼴을 윤곽선으로 바꾼 문서는 화면에는 글이 가득하지만 글자 층이 비어 있다. Docling 은
비트맵 영역에만 OCR 을 돌리므로 이런 쪽의 본문, 표 칸을 하나도 읽지 못한다. 만도 패드 분류 보고서(95쪽 가운데
78쪽), 열차 신호설비 보고서(49쪽 가운데 31쪽)가 이렇게 본문을 통째로 잃었다(2026-11-25 전체 대조).

윤곽선 쪽은 글자 층 글이 거의 없고, 쪽을 덮는 그림도 없으며, 그린 도형이 많은 쪽으로 본다. 그림이 덮는 쪽은
Docling OCR 이 읽고, 도형이 적은 쪽은 빈 쪽이나 간지다.
"""
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# 글자 층 글(공백 뺀 글자 수)이 이보다 적으면 글자 층으로 읽을 수 없는 쪽이다(pdf_adapter 의 믿을 만한 글자 수와 같다)
_MAX_NATIVE_CHARS = 50
# 쪽 넓이에서 그림이 이만큼 넘게 덮으면 그림 쪽이다(Docling OCR 이 읽는다)
_MAX_IMAGE_SHARE = 0.3
# 그린 도형이 이보다 적으면 빈 쪽이나 간지다. 실측한 윤곽선 쪽은 쪽마다 수백 개였다
_MIN_DRAWINGS = 100


def _is_outline_page(page) -> bool:
    import fitz

    if len("".join(page.get_text().split())) >= _MAX_NATIVE_CHARS:
        return False
    area = page.rect.width * page.rect.height
    if area <= 0:
        return False
    covered = sum(abs(fitz.Rect(info["bbox"]) & page.rect) for info in page.get_image_info())
    if covered / area > _MAX_IMAGE_SHARE:
        return False
    return len(page.get_drawings()) >= _MIN_DRAWINGS


def _scan(path: Path) -> tuple[list[int], int]:
    """(윤곽선 쪽 번호 목록, 전체 쪽 수). 열지 못하면 ([], 0)."""
    try:
        import fitz

        with fitz.open(str(path)) as pdf:
            return [page.number + 1 for page in pdf if _is_outline_page(page)], len(pdf)
    except Exception:  # noqa: BLE001 - 엔진 고르기의 보조 신호다. 못 읽으면 윤곽선 쪽이 없다고 본다
        logger.debug("윤곽선 쪽을 세지 못했다: %s", path.name, exc_info=True)
        return [], 0


def outline_text_pages(path: Path) -> list[int]:
    """글자를 윤곽선으로 그린 쪽 번호(1부터)."""
    return _scan(path)[0]


def outline_text_share(path: Path) -> float:
    """전체 쪽 가운데 윤곽선 쪽의 비율. 열지 못하면 0."""
    pages, total = _scan(path)
    return len(pages) / total if total else 0.0
