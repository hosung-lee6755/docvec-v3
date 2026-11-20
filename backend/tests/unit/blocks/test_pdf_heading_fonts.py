"""PDF 제목 요소의 실제 글자 크기 읽기(pdf_heading_fonts.py, 2026-11-20)."""
import pytest

from app.pipeline.blocks.pdf_heading_fonts import heading_font_sizes

fitz = pytest.importorskip("fitz")


def _pdf_with_lines(lines):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    for y, size, text in lines:
        page.insert_text((50, y), text, fontsize=size)
    data = doc.tobytes()
    doc.close()
    return data


def test_reads_the_dominant_span_size_inside_a_bottom_left_origin_bbox():
    pdf = _pdf_with_lines([(100, 18, "Chapter One"), (200, 10.5, "Section A")])
    # Docling 좌표는 왼쪽 아래 원점이다. y=100 기준선 줄은 위에서 약 84~104pt 에 있다
    elements = [
        {"id": "big", "type": "section_header", "page": 1, "bbox": [45, 842 - 82, 200, 842 - 106]},
        {"id": "small", "type": "section_header", "page": 1, "bbox": [45, 842 - 190, 200, 842 - 204]},
        {"id": "body", "type": "text", "page": 1, "bbox": [45, 842 - 190, 200, 842 - 204]},
    ]

    sizes = heading_font_sizes(pdf, elements)

    assert sizes == {"big": 18.0, "small": 10.5}


def test_returns_empty_when_the_pdf_cannot_be_read():
    elements = [{"id": "h", "type": "section_header", "page": 1, "bbox": [0, 10, 10, 0]}]
    assert heading_font_sizes(b"not a pdf", elements) == {}
    assert heading_font_sizes(b"", elements) == {}
