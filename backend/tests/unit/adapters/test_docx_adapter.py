from docx import Document as DocxDocument
from docx.shared import Pt

from app.pipeline.adapters.docx_adapter import DOCXAdapter


def _make_docx_with_heading_and_body(tmp_path):
    doc = DocxDocument()
    doc.add_heading("Document Title", level=1)
    body = doc.add_paragraph("Regular body paragraph text.")
    body.runs[0].font.size = Pt(11)
    path = tmp_path / "styled.docx"
    doc.save(str(path))
    return path


def test_line_layout_captures_style_name_and_font_size(tmp_path):
    path = _make_docx_with_heading_and_body(tmp_path)

    result = DOCXAdapter().extract(path, {})

    lines = result.metadata["line_layout"]
    heading_line = next(line for line in lines if "Title" in line["text"])
    body_line = next(line for line in lines if "body paragraph" in line["text"].lower())
    assert heading_line["style_name"] == "Heading 1"
    assert body_line["font_size"] == 11.0
    assert body_line["style_name"] != "Heading 1"


def test_line_layout_bold_run_is_detected(tmp_path):
    doc = DocxDocument()
    p = doc.add_paragraph()
    run = p.add_run("Bold statement.")
    run.bold = True
    path = tmp_path / "bold.docx"
    doc.save(str(path))

    result = DOCXAdapter().extract(path, {})

    line = next(line for line in result.metadata["line_layout"] if "Bold statement" in line["text"])
    assert line["is_bold"] is True


def test_extract_font_signals_option_disables_line_layout(tmp_path):
    # 문서 파싱 고도화 Phase 3 config toggle (TextExtractConfig.extract_font_signals).
    path = _make_docx_with_heading_and_body(tmp_path)

    result = DOCXAdapter().extract(path, {"extract_font_signals": False})

    assert result.metadata["line_layout"] == []


def test_line_layout_does_not_alter_text_block_content(tmp_path):
    path = _make_docx_with_heading_and_body(tmp_path)

    result = DOCXAdapter().extract(path, {})

    # line_layout is a side artifact alongside the per-paragraph text blocks,
    # not a replacement — each paragraph is still its own block (see
    # test_paragraphs_and_tables_preserve_document_reading_order for why
    # paragraphs are no longer pre-merged into a single joined block).
    texts = [b.text for b in result.pages[0].text_blocks]
    assert texts == ["Document Title", "Regular body paragraph text."]


def test_paragraphs_and_tables_preserve_document_reading_order(tmp_path):
    # doc.paragraphs and doc.tables are separate flat lists in python-docx —
    # reading them independently loses interleaving: a table sitting between
    # two paragraphs in the source previously ended up after both once
    # extracted. Walking the document body directly must keep the real order
    # (문서 파싱 고도화 회고, 2026-07-23).
    doc = DocxDocument()
    doc.add_paragraph("PARA_ONE")
    table = doc.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "CELL_A"
    table.rows[0].cells[1].text = "CELL_B"
    doc.add_paragraph("PARA_TWO")
    path = tmp_path / "order.docx"
    doc.save(str(path))

    result = DOCXAdapter().extract(path, {})

    texts = [b.text for b in result.pages[0].text_blocks]
    assert texts[0] == "PARA_ONE"
    assert "CELL_A" in texts[1] and "CELL_B" in texts[1]
    assert texts[2] == "PARA_TWO"
