"""윤곽선 글자 표의 칸 OCR(2026-11-27, 법령심사 보고서 7쪽 "필수 데이터 8종" 표)."""
import fitz
import pytest

from app.pipeline.adapters import outline_table_cells as otc

# 3×3 격자. 진짜 표로 볼 만큼 칸이 많다
CELLS = [(50.0 + 60 * c, 50.0 + 30 * r, 110.0 + 60 * c, 80.0 + 30 * r) for r in range(3) for c in range(3)]


def _pdf(tmp_path, glyph_shapes: int, cells=CELLS, with_image: bool = False):
    doc = fitz.open()
    page = doc.new_page(width=300, height=200)
    for cell in cells:
        page.draw_rect(fitz.Rect(*cell))
    # 윤곽선 글자 대신 칸 안에 작은 도형을 그린다
    for i in range(glyph_shapes):
        x = 55 + (i % 40) * 4.5
        page.draw_rect(fitz.Rect(x, 60, x + 2, 66), fill=(0, 0, 0))
    if with_image:
        pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 20, 20), False)
        page.insert_image(fitz.Rect(50, 50, 230, 140), pixmap=pixmap)
    path = tmp_path / f"outline_{glyph_shapes}_{len(cells)}_{with_image}.pdf"
    doc.save(path)
    return path


@pytest.fixture
def fake_ocr(monkeypatch):
    calls: list = []
    monkeypatch.setattr(otc, "mean_confidence", lambda page, bbox: 90.0)
    monkeypatch.setattr(otc, "ocr_cells", lambda page, boxes: calls.append(boxes) or {boxes[0]: "법령 데이터"})
    return calls


def test_cells_of_a_table_drawn_with_outline_glyphs_are_read_by_ocr(tmp_path, fake_ocr):
    warnings: list[str] = []
    reader = otc.OutlineTableReader(_pdf(tmp_path, 40), warnings)

    texts = reader.read(1, CELLS)
    reader.close()

    assert texts == {CELLS[0]: "법령 데이터"}
    assert any("윤곽선" in w for w in warnings)


def test_an_empty_form_table_with_few_drawings_is_not_ocred(tmp_path, fake_ocr):
    # 빈 서식 표(신청 대장)는 칸 선만 있다. 예전처럼 버리도록 None 을 돌려준다
    reader = otc.OutlineTableReader(_pdf(tmp_path, 0), [])

    assert reader.read(1, CELLS) is None
    reader.close()
    assert fake_ocr == []


def test_a_diagram_frame_with_few_cells_is_not_ocred(tmp_path, fake_ocr):
    # 법령심사 보고서 8쪽 도식 틀(칸 2~6개)은 OCR 글이 깨졌다
    frame = CELLS[:2]
    reader = otc.OutlineTableReader(_pdf(tmp_path, 40, cells=frame), [])

    assert reader.read(1, frame) is None
    reader.close()
    assert fake_ocr == []


def test_a_frame_covered_by_a_screenshot_is_not_ocred(tmp_path, fake_ocr):
    reader = otc.OutlineTableReader(_pdf(tmp_path, 40, with_image=True), [])

    assert reader.read(1, CELLS) is None
    reader.close()
    assert fake_ocr == []


def test_a_table_read_with_low_confidence_is_dropped(tmp_path, monkeypatch, fake_ocr):
    monkeypatch.setattr(otc, "mean_confidence", lambda page, bbox: 40.0)
    reader = otc.OutlineTableReader(_pdf(tmp_path, 40), [])

    assert reader.read(1, CELLS) is None
    reader.close()
    assert fake_ocr == []


def test_a_failure_leaves_a_warning_and_keeps_the_old_behaviour(tmp_path):
    warnings: list[str] = []
    reader = otc.OutlineTableReader(tmp_path / "missing.pdf", warnings)

    assert reader.read(1, CELLS) is None
    assert warnings and "윤곽선" in warnings[0]
