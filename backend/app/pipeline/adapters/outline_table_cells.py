"""윤곽선 글자로 그린 표의 칸을 OCR 로 읽는다(2026-11-27).

PPT 에서 내보낸 PDF 는 표 안의 글자를 글꼴 대신 윤곽선 도형으로 그리기도 한다. 선 표 찾기는 표 틀과 칸을 찾지만
칸의 글이 비어, 빈 표로 버려졌다. 쪽 전체 OCR 은 그 쪽의 진짜 글자(제목, 문단)가 50자를 넘으면 하지 않으므로
표가 통째로 사라졌다(법령심사 자동화 분석결과보고서 7쪽 "필수 데이터 8종" 표, 곡선 도형 1,073개).

칸이 모두 빈 표 안에 그린 도형이 많으면 윤곽선 글자 표로 보고, 표 영역만 한 번 렌더링해 칸마다 OCR 한다.
쪽 전체 OCR 여부를 정하는 기준은 그대로 둔다.
"""
import io
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

Box = tuple[float, float, float, float]

# 표 영역 안의 그린 도형이 이보다 적으면 빈 서식 표(신청 대장 등)로 본다. 윤곽선 글자는 글자마다 도형 하나 이상이다
MIN_DRAWINGS_IN_TABLE = 30
# 칸이 이보다 적은 틀은 도식의 상자다. 법령심사 보고서 8쪽 도식 틀은 칸 2~6개였고 OCR 글이 "BY TI AILII …"처럼
# 깨졌다. 같은 문서의 진짜 표는 칸 46개, 128개였다(2026-11-27 실측)
MIN_CELLS = 8
# 표 영역 전체 OCR 의 낱말 평균 신뢰도(0~100)가 이보다 낮으면 버린다. 실측한 진짜 표는 70.9~94.8 이었다
MIN_MEAN_CONFIDENCE = 60.0
# 표 영역을 그림이 이만큼 넘게 덮으면 화면 캡처를 담은 도식이다. 윤곽선 글자는 그림이 아니라 도형이다
MAX_IMAGE_SHARE = 0.3
_RENDER_DPI = 300
# 칸 선이 글자로 읽히지 않게 칸 안쪽으로 줄이는 폭(pt)
_CELL_INSET = 1.5
# 한 칸은 여러 줄일 수 있으므로 문단 하나로 본다. 쪽 OCR(psm 4)과 달리 칸 하나를 한 덩어리로 읽는다
_TESSERACT_CELL_CONFIG = "--oem 1 --psm 6"
DETECTED_AS = "outline_ocr"
CONFIDENCE = 0.6


def _overlaps(rect: Box, box: Box) -> bool:
    return rect[0] < box[2] and rect[2] > box[0] and rect[1] < box[3] and rect[3] > box[1]


def drawings_inside(fitz_page, bbox: Box) -> int:
    """표 영역과 겹치는 그린 도형 수."""
    count = 0
    for drawing in fitz_page.get_drawings():
        rect = drawing.get("rect")
        if rect is not None and _overlaps((rect.x0, rect.y0, rect.x1, rect.y1), bbox):
            count += 1
    return count


def image_share(fitz_page, bbox: Box) -> float:
    """표 영역에서 그림이 덮는 넓이의 비율."""
    area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
    if area <= 0:
        return 0.0
    covered = 0.0
    for info in fitz_page.get_image_info():
        x0, y0, x1, y1 = info["bbox"]
        width = min(x1, bbox[2]) - max(x0, bbox[0])
        height = min(y1, bbox[3]) - max(y0, bbox[1])
        if width > 0 and height > 0:
            covered += width * height
    return covered / area


def mean_confidence(fitz_page, bbox: Box) -> float | None:
    """표 영역 전체를 한 번 OCR 한 낱말 평균 신뢰도(0~100). 낱말이 없으면 None."""
    import fitz
    import pytesseract
    from PIL import Image

    pixmap = fitz_page.get_pixmap(dpi=_RENDER_DPI, clip=fitz.Rect(*bbox))
    image = Image.open(io.BytesIO(pixmap.tobytes("png"))).convert("L")
    data = pytesseract.image_to_data(
        image, lang="kor+eng", config=_TESSERACT_CELL_CONFIG, output_type=pytesseract.Output.DICT,
    )
    scores = []
    for word, conf in zip(data["text"], data["conf"], strict=False):
        try:
            value = float(conf)
        except (TypeError, ValueError):
            continue
        if word.strip() and value >= 0:
            scores.append(value)
    return sum(scores) / len(scores) if scores else None


def _union(boxes: list[Box]) -> Box:
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def _ocr(image) -> str:
    import pytesseract

    text = pytesseract.image_to_string(image.convert("L"), lang="kor+eng", config=_TESSERACT_CELL_CONFIG)
    return " ".join(text.split())


def ocr_cells(fitz_page, boxes: list[Box]) -> dict[Box, str]:
    """칸 좌표(위쪽 원점, pt) → OCR 글. 표 영역을 한 번만 렌더링해 칸마다 잘라 읽는다."""
    import fitz
    from PIL import Image

    if not boxes:
        return {}
    area = _union(boxes)
    scale = _RENDER_DPI / 72
    pixmap = fitz_page.get_pixmap(dpi=_RENDER_DPI, clip=fitz.Rect(*area))
    image = Image.open(io.BytesIO(pixmap.tobytes("png")))
    texts: dict[Box, str] = {}
    for box in boxes:
        left = max(0, int((box[0] - area[0] + _CELL_INSET) * scale))
        top = max(0, int((box[1] - area[1] + _CELL_INSET) * scale))
        right = min(image.width, int((box[2] - area[0] - _CELL_INSET) * scale))
        bottom = min(image.height, int((box[3] - area[1] - _CELL_INSET) * scale))
        if right - left < 4 or bottom - top < 4:
            continue
        text = _ocr(image.crop((left, top, right, bottom)))
        if text:
            texts[box] = text
    return texts


class OutlineTableReader:
    """쪽마다 PDF 를 다시 열지 않도록 문서 하나를 열어 두고 윤곽선 글자 표의 칸을 읽는다."""

    def __init__(self, path: Path, warnings: list[str]) -> None:
        self._path = path
        self._warnings = warnings
        self._doc = None
        self._failed = False

    def read(self, page_number: int, boxes: list[Box]) -> dict[Box, str] | None:
        """윤곽선 글자 표이면 칸 → 글, 아니면 None. 실패하면 경고를 남기고 None(지금처럼 표를 버린다)."""
        if self._failed or len(boxes) < MIN_CELLS:
            return None
        try:
            if self._doc is None:
                import fitz

                self._doc = fitz.open(str(self._path))
            page = self._doc[page_number - 1]
            area = _union(boxes)
            if drawings_inside(page, area) < MIN_DRAWINGS_IN_TABLE or image_share(page, area) > MAX_IMAGE_SHARE:
                return None
            confidence = mean_confidence(page, area)
            if confidence is None or confidence < MIN_MEAN_CONFIDENCE:
                return None
            texts = ocr_cells(page, boxes)
        except Exception as exc:  # noqa: BLE001 - 보강일 뿐이다. 실패하면 예전처럼 빈 표를 버린다
            self._failed = self._doc is None
            self._warnings.append(f"page {page_number} 윤곽선 글자 표를 읽지 못했습니다: {exc}")
            logger.warning("outline table OCR failed on page %s: %s", page_number, exc)
            return None
        if texts:
            self._warnings.append(
                f"page {page_number} 표의 글자가 윤곽선 도형이라 칸 {len(texts)}개를 OCR 로 읽었습니다. 오독이 있을 수 있습니다."
            )
        return texts or None

    def close(self) -> None:
        if self._doc is not None:
            self._doc.close()
            self._doc = None
