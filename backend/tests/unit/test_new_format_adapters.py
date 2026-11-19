"""XLSX, PPTX, TXT, MD, HTML, 이미지 어댑터(전체 점검 1-2)."""
from datetime import datetime
from pathlib import Path

import pytest

from app.pipeline.adapters import UnsupportedFileTypeError, get_adapter
from app.pipeline.adapters.sheet_adapter import SheetAdapter, cell_text
from app.pipeline.adapters.simple_layout import BODY_FONT_SIZE
from app.pipeline.adapters.text_adapter import decode_text, parse_html, parse_plain_text
from app.pipeline.formats import EXTENSION_CONTENT_TYPES, SUPPORTED_SUFFIXES, is_supported


def _texts(parsed):
    return [b.text for page in parsed.pages for b in page.text_blocks]


@pytest.mark.parametrize("name, adapter", [
    ("a.xlsx", "SheetAdapter"), ("a.PPTX", "SlideAdapter"), ("a.txt", "TextAdapter"), ("a.md", "TextAdapter"),
    ("a.html", "HtmlAdapter"), ("a.htm", "HtmlAdapter"), ("a.png", "ImageAdapter"), ("a.JPG", "ImageAdapter"),
    ("a.tiff", "ImageAdapter"), ("a.pdf", "PDFAdapter"), ("a.docx", "DOCXAdapter"), ("a.CSV", "CsvAdapter"),
])
def test_get_adapter_routes_by_extension(name, adapter):
    assert type(get_adapter(Path(name), "")).__name__ == adapter


def test_unsupported_extension_lists_the_supported_formats():
    with pytest.raises(UnsupportedFileTypeError, match="XLSX"):
        get_adapter(Path("a.exe"), "")


def test_html_and_markdown_are_never_stored_as_html():
    assert {EXTENSION_CONTENT_TYPES[s] for s in (".html", ".htm", ".md", ".txt")} == {"text/plain"}
    assert is_supported("보고서.XLSX") and not is_supported("a.svg") and ".exe" not in SUPPORTED_SUFFIXES


def test_decode_text_reads_utf8_bom_and_cp949():
    assert decode_text("﻿한글".encode("utf-8")) == "한글"
    assert decode_text("한글 메모".encode("cp949")) == "한글 메모"


def test_plain_text_splits_paragraphs_on_blank_lines_and_ignores_markdown_marks():
    blocks, tables, collector = parse_plain_text("# 제목 아님\r\n첫 줄\n\n둘째 문단\n", is_markdown=False)

    assert [b.text for b in blocks] == ["# 제목 아님\n첫 줄", "둘째 문단"]
    assert not tables and all(e["style_name"] is None for e in collector.line_layout)


def test_markdown_headings_tables_and_code_fences():
    source = "# 개요\n본문 한 줄\n## 세부 ##\n| 항목 | 값 |\n|---|:--:|\n| 가 | 1 |\n\n```\n# 코드 안의 샵\n\n| a |\n```\n끝"

    blocks, tables, collector = parse_plain_text(source, is_markdown=True)

    assert [b.text for b in blocks][:3] == ["개요", "본문 한 줄", "세부"]
    assert tables[0].rows == [["항목", "값"], ["가", "1"]]
    assert blocks[3].block_type == "table" and blocks[3].text.startswith("[표 1]")
    # 코드 울타리 안은 제목이나 표로 읽지 않는다
    assert "# 코드 안의 샵" in blocks[4].text and len(tables) == 1
    headings = [(e["text"], e["style_name"]) for e in collector.line_layout if e["style_name"]]
    assert headings == [("개요", "Heading 1"), ("세부", "Heading 2")]
    sizes = {e["text"]: e["font_size"] for e in collector.line_layout}
    assert sizes["개요"] > sizes["세부"] > sizes["본문 한 줄"] == BODY_FONT_SIZE


def test_html_drops_scripts_and_keeps_headings_tables_and_text_order():
    html = (
        "<html><head><title> 안내문 </title><style>p{}</style></head><body>"
        "<script>alert(1)</script><h1>모집 <b>공고</b></h1><p>첫 문단<br>둘째 줄</p>"
        "<ul><li>항목 하나</li><li>항목 둘</li></ul>"
        "<table><tr><th>구분</th><th>내용</th></tr>"
        "<tr><td>기간</td><td><table><tr><td>안쪽</td></tr></table>3일</td></tr></table>"
        "<div>꼬리<!-- 주석 --></div></body></html>"
    )

    blocks, tables, collector, title = parse_html(html)

    texts = [b.text for b in blocks]
    assert title == "안내문"
    assert texts[:4] == ["모집 공고", "첫 문단\n둘째 줄", "항목 하나", "항목 둘"]
    assert texts[-1] == "꼬리" and not any("alert" in t or "주석" in t for t in texts)
    assert len(tables) == 1 and tables[0].rows == [["구분", "내용"], ["기간", "안쪽 3일"]]
    assert collector.line_layout[0]["style_name"] == "Heading 1"


def test_text_and_html_adapters_return_single_page_documents(tmp_path):
    md = tmp_path / "a.md"
    md.write_text("# 제목\n본문", encoding="utf-8")
    html = tmp_path / "a.html"
    html.write_text("<title>T</title><p>본문</p>", encoding="utf-8")

    parsed_md = get_adapter(md, "").extract(md, {})
    parsed_html = get_adapter(html, "").extract(html, {})

    assert (parsed_md.format_id, parsed_md.page_count, _texts(parsed_md)) == ("markdown", 1, ["제목", "본문"])
    assert parsed_html.format_id == "html" and parsed_html.metadata["document_title"] == "T"


def test_cell_text_formats_numbers_dates_and_booleans():
    assert [cell_text(v) for v in (None, 3.0, 0.125, True, " 가 ")] == ["", "3", "0.125", "TRUE", "가"]
    assert cell_text(datetime(2026, 1, 2)) == "2026-01-02"
    assert cell_text(datetime(2026, 1, 2, 3, 4, 5)) == "2026-01-02 03:04:05"


def test_xlsx_sheets_become_pages_with_tables_split_on_blank_rows(tmp_path):
    from openpyxl import Workbook

    workbook = Workbook()
    first = workbook.active
    first.title = "매출"
    for row in (["분기", "금액"], ["1분기", 1200.0], [], ["비고: 잠정치"], [], ["담당", "부서", None], ["김", "영업", None]):
        first.append(row)
    workbook.create_sheet("빈 시트")
    path = tmp_path / "a.xlsx"
    workbook.save(path)

    parsed = SheetAdapter().extract(path, {})

    assert parsed.page_count == 2 and [p.page_number for p in parsed.pages] == [1, 2]
    page = parsed.pages[0]
    assert [t.rows for t in page.table_candidates] == [[["분기", "금액"], ["1분기", "1200"]], [["담당", "부서"], ["김", "영업"]]]
    assert [b.text.split("\n")[0] for b in page.text_blocks] == ["매출", "[표 1]", "비고: 잠정치", "[표 2]"]
    assert _texts(parsed)[-1] == "빈 시트"
    assert parsed.metadata["line_layout"][0]["style_name"] == "Heading 1"


def test_xlsx_row_limit_is_reported(tmp_path, monkeypatch):
    from openpyxl import Workbook

    from app.pipeline.adapters import sheet_adapter

    monkeypatch.setattr(sheet_adapter, "MAX_ROWS_PER_SHEET", 2)
    workbook = Workbook()
    for i in range(5):
        workbook.active.append([i, i])
    path = tmp_path / "a.xlsx"
    workbook.save(path)

    parsed = SheetAdapter().extract(path, {})

    assert len(parsed.pages[0].table_candidates[0].rows) == 2 and "2행까지만" in parsed.warnings[0]


def test_csv_is_a_supported_format_stored_as_plain_text():
    assert is_supported("목록.CSV") and EXTENSION_CONTENT_TYPES[".csv"] == "text/plain"


def test_csv_becomes_one_page_with_tables_split_on_blank_rows(tmp_path):
    from app.pipeline.adapters.sheet_adapter import CsvAdapter

    # 처리 단계는 임시 파일 이름으로 넘기므로, 제목은 원래 파일 이름(options)에서 가져온다
    path = tmp_path / "tmpk3x9.csv"
    path.write_text("﻿분기,금액\n1분기,1200\n\n비고: 잠정치\n\n담당,부서\n김,\"영업, 1팀\"\n", encoding="utf-8")

    parsed = CsvAdapter().extract(path, {"original_filename": "매출.csv"})

    assert parsed.format_id == "csv" and parsed.page_count == 1 and not parsed.warnings
    page = parsed.pages[0]
    assert [t.rows for t in page.table_candidates] == [[["분기", "금액"], ["1분기", "1200"]], [["담당", "부서"], ["김", "영업, 1팀"]]]
    assert [b.text.split("\n")[0] for b in page.text_blocks] == ["매출", "[표 1]", "비고: 잠정치", "[표 2]"]


@pytest.mark.parametrize("delimiter", [";", "\t", "|"])
def test_csv_reads_cp949_and_other_delimiters(tmp_path, delimiter):
    from app.pipeline.adapters.sheet_adapter import CsvAdapter

    path = tmp_path / "a.csv"
    path.write_bytes(delimiter.join(["이름", "부서"]).encode("cp949") + b"\r\n" + delimiter.join(["홍길동", "총무"]).encode("cp949"))

    parsed = CsvAdapter().extract(path, {})

    assert parsed.pages[0].table_candidates[0].rows == [["이름", "부서"], ["홍길동", "총무"]]


def test_csv_row_limit_is_reported(tmp_path, monkeypatch):
    from app.pipeline.adapters import sheet_adapter

    monkeypatch.setattr(sheet_adapter, "MAX_ROWS_PER_SHEET", 2)
    path = tmp_path / "a.csv"
    path.write_text("\n".join(f"{i},{i}" for i in range(5)), encoding="utf-8")

    parsed = sheet_adapter.CsvAdapter().extract(path, {})

    assert len(parsed.pages[0].table_candidates[0].rows) == 2 and "2행까지만" in parsed.warnings[0]


def test_csv_without_original_name_has_no_title_line(tmp_path):
    from app.pipeline.adapters.sheet_adapter import CsvAdapter

    path = tmp_path / "tmpk3x9.csv"
    path.write_text("이름,부서\n홍길동,총무\n", encoding="utf-8")

    parsed = CsvAdapter().extract(path, {})

    assert [b.text.split("\n")[0] for b in parsed.pages[0].text_blocks] == ["[표 1]"]


def test_empty_csv_returns_a_warning(tmp_path):
    from app.pipeline.adapters.sheet_adapter import CsvAdapter

    path = tmp_path / "a.csv"
    path.write_bytes(b"")

    parsed = CsvAdapter().extract(path, {})

    assert parsed.pages == [] and parsed.warnings


def test_broken_files_return_a_warning_instead_of_raising(tmp_path):
    for name in ("a.xlsx", "a.pptx", "a.png"):
        path = tmp_path / name
        path.write_bytes(b"not a real file")
        parsed = get_adapter(path, "").extract(path, {})
        assert parsed.pages == [] and parsed.warnings


def test_pptx_slides_become_pages_with_title_table_picture_and_notes(tmp_path):
    import io

    from PIL import Image
    from pptx import Presentation
    from pptx.util import Inches

    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[5])
    slide.shapes.title.text = "분기 실적"
    box = slide.shapes.add_textbox(Inches(1), Inches(2), Inches(4), Inches(1))
    box.text_frame.text = "매출이 늘었다"
    table = slide.shapes.add_table(2, 2, Inches(1), Inches(3), Inches(4), Inches(1)).table
    for (r, c), value in {(0, 0): "항목", (0, 1): "값", (1, 0): "매출", (1, 1): "12"}.items():
        table.cell(r, c).text = value
    image = io.BytesIO()
    Image.new("RGB", (40, 40), "red").save(image, "PNG")
    image.seek(0)
    slide.shapes.add_picture(image, Inches(6), Inches(5))
    slide.notes_slide.notes_text_frame.text = "강조할 것"
    presentation.slides.add_slide(presentation.slide_layouts[6])
    path = tmp_path / "a.pptx"
    presentation.save(path)

    parsed = get_adapter(path, "").extract(path, {})

    first = parsed.pages[0]
    assert parsed.format_id == "pptx" and parsed.page_count == 2
    assert [b.text.split("\n")[0] for b in first.text_blocks] == ["분기 실적", "매출이 늘었다", "[표 1]", "발표자 노트: 강조할 것"]
    assert first.table_candidates[0].rows == [["항목", "값"], ["매출", "12"]]
    assert len(first.image_regions) == 1 and first.image_regions[0].image_bytes.startswith(b"\x89PNG")
    assert first.width == pytest.approx(720) and parsed.pages[1].text_blocks == []
    heading = parsed.metadata["line_layout"][0]
    assert (heading["text"], heading["style_name"]) == ("분기 실적", "Heading 1")


def test_image_is_converted_to_pdf_and_sent_through_the_pdf_adapter(tmp_path, monkeypatch):
    from PIL import Image

    from app.pipeline.adapters import pdf_adapter
    from app.pipeline.adapters.base import RawParsedDocument

    seen = {}

    def fake_extract(self, file_path, options):
        seen["suffix"], seen["head"], seen["options"] = file_path.suffix, file_path.read_bytes()[:5], options
        return RawParsedDocument(format_id="pdf", page_count=1, pages=[], metadata={}, warnings=[])

    monkeypatch.setattr(pdf_adapter.PDFAdapter, "extract", fake_extract)
    path = tmp_path / "scan.png"
    Image.new("RGB", (60, 80), "white").save(path)

    parsed = get_adapter(path, "").extract(path, {"x": 1})

    assert seen == {"suffix": ".pdf", "head": b"%PDF-", "options": {"x": 1}}
    assert parsed.format_id == "image" and parsed.page_count == 1


def test_html_buttons_are_page_controls_not_document_text():
    # 고도화보고서: 목차 머리의 <a>제목</a><button>목차</button>이 "…보고서목차"로 붙어 첫 청크가 됐다(2026-11-19)
    from app.pipeline.adapters.text_adapter import parse_html

    html = (
        '<body><nav><div class="toc-head"><a href="#top">분석 보고서</a>'
        '<button type="button">목차</button></div></nav>'
        '<p>본문 <select><option>선택</option></select>입니다.</p></body>'
    )
    blocks, _tables, _collector, _title = parse_html(html)
    assert [b.text for b in blocks] == ["분석 보고서", "본문 입니다."]
