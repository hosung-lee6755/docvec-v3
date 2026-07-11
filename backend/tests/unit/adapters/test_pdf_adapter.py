from pathlib import Path

import fitz
import pytest

from app.pipeline.adapters.pdf_adapter import PDFAdapter


def _make_pdf_with_text_and_image(tmp_path: Path) -> Path:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Hello World bbox regression check", fontsize=12)
    pix = fitz.Pixmap(fitz.csRGB, (0, 0, 100, 50))
    pix.set_rect(pix.irect, (255, 0, 0))
    page.insert_image(fitz.Rect(50, 300, 150, 350), pixmap=pix)
    path = tmp_path / "sample.pdf"
    doc.save(str(path))
    return path


def test_native_text_block_gets_real_bbox_not_none_or_zeroed(tmp_path):
    pdf_path = _make_pdf_with_text_and_image(tmp_path)

    result = PDFAdapter().extract(pdf_path, {})

    text_block = result.pages[0].text_blocks[0]
    assert text_block.bbox is not None
    assert text_block.bbox != (0, 0, 0, 0)
    x0, top, x1, bottom = text_block.bbox
    assert x0 < x1
    assert top < bottom


def test_image_region_gets_real_placement_bbox_not_dummy_zero(tmp_path):
    pdf_path = _make_pdf_with_text_and_image(tmp_path)

    result = PDFAdapter().extract(pdf_path, {})

    image_regions = result.pages[0].image_regions
    assert len(image_regions) == 1
    assert image_regions[0].bbox == pytest.approx((50.0, 300.0, 150.0, 350.0))


def test_image_region_bbox_matches_actual_placement_rect(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    pix = fitz.Pixmap(fitz.csRGB, (0, 0, 40, 40))
    pix.set_rect(pix.irect, (0, 255, 0))
    placement = fitz.Rect(200, 400, 260, 470)
    page.insert_image(placement, pixmap=pix)
    path = tmp_path / "image_only.pdf"
    doc.save(str(path))

    result = PDFAdapter().extract(path, {})

    assert result.pages[0].image_regions[0].bbox == pytest.approx(
        (placement.x0, placement.y0, placement.x1, placement.y1)
    )


def test_page_with_no_images_returns_no_image_regions(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Text only page, no images here")
    path = tmp_path / "text_only.pdf"
    doc.save(str(path))

    result = PDFAdapter().extract(path, {})

    assert result.pages[0].image_regions == []
