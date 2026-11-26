"""글자를 윤곽선으로 그린 쪽 찾기. 이런 쪽은 글자 층이 비어 Docling 이 본문을 읽지 못한다(2026-11-25)."""
import fitz

from app.pipeline.adapters.pdf_outline_text import outline_text_pages, outline_text_share


def _pdf(tmp_path):
    pdf = fitz.open()
    text_page = pdf.new_page()
    text_page.insert_text((50, 80), "Native text layer line " * 4)
    outline_page = pdf.new_page()
    for i in range(150):  # 글자 윤곽선 대신 짧은 선을 많이 그린다
        outline_page.draw_line((50 + i, 100), (52 + i, 110))
    pdf.new_page()  # 빈 쪽
    path = tmp_path / "mixed.pdf"
    pdf.save(path)
    return path


def test_outline_text_pages_finds_pages_drawn_without_a_text_layer(tmp_path):
    assert outline_text_pages(_pdf(tmp_path)) == [2]


def test_outline_text_share_counts_against_all_pages(tmp_path):
    assert outline_text_share(_pdf(tmp_path)) == 1 / 3


def test_unreadable_file_has_no_outline_pages(tmp_path):
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"not a pdf")
    assert outline_text_pages(broken) == [] and outline_text_share(broken) == 0.0
