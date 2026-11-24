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


def test_extract_reports_core_title_and_word_page_count(tmp_path):
    import zipfile

    from docx import Document

    doc = Document()
    doc.add_paragraph("본문")
    doc.core_properties.title = "AIDE 검수 기준서 v1.3"
    path = tmp_path / "titled.docx"
    doc.save(path)
    # Word 가 저장 시 app.xml 에 남기는 쪽수를 흉내 낸다(python-docx 는 쓰지 않는다).
    with zipfile.ZipFile(path, "a") as archive:
        archive.writestr(
            "docProps/app.xml",
            '<?xml version="1.0" encoding="UTF-8"?><Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"><Pages>5</Pages><Words>522</Words></Properties>',
        )

    result = DOCXAdapter().extract(path, {})

    assert result.metadata["document_title"] == "AIDE 검수 기준서 v1.3"
    assert result.metadata["document_pages"] == 5


def test_extract_without_core_title_reports_no_title(tmp_path):
    from docx import Document

    doc = Document()
    doc.add_paragraph("본문")
    path = tmp_path / "plain.docx"
    doc.save(path)

    result = DOCXAdapter().extract(path, {})

    assert not result.metadata["document_title"]


def test_word_page_count_ignores_template_placeholder_without_word_statistics(tmp_path):
    # 생성기(docx-js 등)가 만든 문서는 app.xml 이 템플릿 값(Pages=1, Words=0)이라 실제 쪽수가 아니다.
    import zipfile

    from docx import Document

    from app.pipeline.adapters.docx_adapter import _word_page_count

    path = tmp_path / "generated.docx"
    Document().save(path)
    with zipfile.ZipFile(path, "a") as archive:
        archive.writestr(
            "docProps/app.xml",
            '<?xml version="1.0"?><Properties><Pages>1</Pages><Words>0</Words></Properties>',
        )

    assert _word_page_count(path) is None


def test_word_page_count_is_none_when_the_file_has_no_app_properties(tmp_path):
    from app.pipeline.adapters.docx_adapter import _word_page_count

    broken = tmp_path / "not-a-zip.docx"
    broken.write_bytes(b"plain bytes")

    assert _word_page_count(broken) is None


def _heading_levels(path):
    return {line["text"]: line.get("heading_level") for line in DOCXAdapter().extract(path, {}).metadata["line_layout"]}


def test_heading_styles_carry_heading_level_like_hwpx_outline_levels(tmp_path):
    # 2026-11-20 감사: 'Heading 1' 스타일만 있고 글자 크기를 문단에 직접 주지 않은 Word 제목("alice")이
    # 구조 분석에서 본문 문단이 됐다. 구조 분석은 heading_level 이 있어야 번호 없는 제목을 제목으로 본다
    doc = DocxDocument()
    doc.add_heading("Report", level=0)
    doc.add_heading("alice", level=1)
    doc.add_heading("Detail", level=2)
    doc.add_paragraph("body text.")
    path = tmp_path / "headings.docx"
    doc.save(str(path))

    levels = _heading_levels(path)

    assert levels == {"Report": 1, "alice": 1, "Detail": 2, "body text.": None}


def test_outline_level_on_paragraph_or_style_sets_heading_level(tmp_path):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    doc = DocxDocument()
    direct = doc.add_paragraph("Direct outline")
    outline = OxmlElement("w:outlineLvl")
    outline.set(qn("w:val"), "1")
    direct._p.get_or_add_pPr().append(outline)
    body = doc.add_paragraph("Body outline nine")
    body_outline = OxmlElement("w:outlineLvl")
    body_outline.set(qn("w:val"), "9")
    body._p.get_or_add_pPr().append(body_outline)
    path = tmp_path / "outline.docx"
    doc.save(str(path))

    levels = _heading_levels(path)

    # w:outlineLvl 은 0부터 센다. 9는 본문 수준이다
    assert levels == {"Direct outline": 2, "Body outline nine": None}


def test_docx_heading_style_becomes_heading_node_in_structure_classification(tmp_path):
    from app.pipeline.blocks.structure_blocks import _classify

    doc = DocxDocument()
    doc.add_heading("alice", level=1)
    doc.add_paragraph("alice personal document body.")
    path = tmp_path / "alice.docx"
    doc.save(str(path))
    layout = DOCXAdapter().extract(path, {}).metadata["line_layout"]

    assert _classify("alice", layout[0], None) == ("HEADING", 1)
    assert _classify("alice personal document body.", layout[1], None) == ("PARAGRAPH", None)


def test_korean_heading_style_name_without_outline_level_sets_heading_level(tmp_path):
    from docx.enum.style import WD_STYLE_TYPE

    doc = DocxDocument()
    doc.styles.add_style("제목 2", WD_STYLE_TYPE.PARAGRAPH)
    doc.add_paragraph("사업 개요", style="제목 2")
    path = tmp_path / "korean.docx"
    doc.save(str(path))

    assert _heading_levels(path) == {"사업 개요": 2}


def _extract_single_table(tmp_path, build):
    doc = DocxDocument()
    table = doc.add_table(rows=3, cols=3)
    build(table)
    path = tmp_path / "merged.docx"
    doc.save(str(path))
    result = DOCXAdapter().extract(path, {})
    (candidate,) = result.pages[0].table_candidates
    table_text = next(b.text for b in result.pages[0].text_blocks if b.block_type == "table")
    return candidate, table_text


def _fill(table, values):
    for r, row in enumerate(values):
        for c, value in enumerate(row):
            if value is not None:
                table.cell(r, c).text = value


def test_horizontally_merged_cell_is_written_once_with_its_span(tmp_path):
    # python-docx 의 row.cells 는 가로로 합친 칸을 열 수만큼 되풀이한다. 그대로 쓰면 "직접인건비 소계 | 직접인건비
    # 소계 | 직접인건비 소계 | 34,000,000"처럼 같은 글이 겹쳐 청크와 표 탭에 들어간다(d5 제안서, 2026-11-24)
    def build(table):
        _fill(table, [["구분", "인원", "금액"], ["PM", "1", "100"], ["소계", None, "100"]])
        table.cell(2, 0).merge(table.cell(2, 1))
        table.cell(2, 0).text = "소계"

    candidate, table_text = _extract_single_table(tmp_path, build)

    assert candidate.rows[2] == ["소계", "", "100"]
    assert candidate.spans == [{"row": 2, "col": 0, "row_span": 1, "col_span": 2}]
    assert table_text.count("소계") == 1


def test_vertically_merged_cell_repeats_down_the_grid_and_reports_its_span(tmp_path):
    # 세로로 합친 칸은 HWP 와 같이 아래 줄에도 글을 되풀이해 줄마다 뜻이 통하게 하고, 화면은 spans 로 합쳐 그린다
    def build(table):
        _fill(table, [["직접 인건비", "PM", "100"], [None, "분석가", "80"], ["경비", "회의비", "10"]])
        table.cell(0, 0).merge(table.cell(1, 0))
        table.cell(0, 0).text = "직접 인건비"

    candidate, _ = _extract_single_table(tmp_path, build)

    assert [row[0] for row in candidate.rows] == ["직접 인건비", "직접 인건비", "경비"]
    assert candidate.spans == [{"row": 0, "col": 0, "row_span": 2, "col_span": 1}]


def test_table_without_merged_cells_has_no_spans(tmp_path):
    candidate, _ = _extract_single_table(
        tmp_path, lambda table: _fill(table, [["가", "나", "다"], ["1", "2", "3"], ["4", "5", "6"]])
    )

    assert candidate.rows == [["가", "나", "다"], ["1", "2", "3"], ["4", "5", "6"]]
    assert not candidate.spans
