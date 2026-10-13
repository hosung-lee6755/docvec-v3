from pathlib import Path

import fitz
import pytest
import pytesseract as real_pytesseract

from app.pipeline.adapters.pdf_adapter import PDFAdapter, _looks_like_list_markers_not_table


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


def test_line_layout_captures_font_size_and_bold_per_line(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 80), "Document Title", fontsize=20, fontname="hebo")
    page.insert_text((72, 120), "Regular body text line.", fontsize=11, fontname="helv")
    # Enough filler text to keep native_text_coverage above the OCR trigger
    # threshold (0.3) — otherwise this near-empty page falls through to the
    # OCR branch, which has no char-level font data at all.
    for i in range(20):
        page.insert_text(
            (72, 150 + i * 14),
            "Filler paragraph line to keep text density high enough.",
            fontsize=11, fontname="helv",
        )
    path = tmp_path / "fonts.pdf"
    doc.save(str(path))

    result = PDFAdapter().extract(path, {})

    lines = result.metadata["line_layout"]
    title_line = next(line for line in lines if "Title" in line["text"])
    body_line = next(line for line in lines if "body" in line["text"].lower())
    assert title_line["font_size"] == pytest.approx(20.0, abs=0.5)
    assert title_line["is_bold"] is True
    assert body_line["font_size"] == pytest.approx(11.0, abs=0.5)
    assert body_line["is_bold"] is False


def test_line_layout_is_empty_for_ocr_pages(tmp_path):
    # A page with no extractable text (blank) forces the OCR branch; OCR'd
    # pages have no char-level font data (pytesseract.image_to_string carries
    # none), so line_layout must stay empty rather than reporting bogus signals.
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    path = tmp_path / "blank.pdf"
    doc.save(str(path))

    result = PDFAdapter().extract(path, {})

    assert result.metadata["line_layout"] == []


def _make_pdf_with_borderless_column_grid(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    rows = [
        ("Header", "Value", "Status"),
        ("RowOne", "111", "OK"),
        ("RowTwo", "222", "OK"),
        ("RowThree", "333", "FAIL"),
    ]
    for i, (c1, c2, c3) in enumerate(rows):
        y = 100 + i * 20
        page.insert_text((72, y), c1, fontsize=11)
        page.insert_text((220, y), c2, fontsize=11)
        page.insert_text((340, y), c3, fontsize=11)
    # Enough surrounding prose that excluding the table region still leaves
    # native_text_coverage above the OCR trigger threshold (0.3) — otherwise
    # the page falls through to the OCR branch, which re-reads the table
    # from the rendered image with no notion of the logical exclusion.
    for i in range(20):
        page.insert_text(
            (72, 220 + i * 14),
            "Filler paragraph line to keep text density high enough.",
            fontsize=11,
        )
    path = tmp_path / "implicit_table.pdf"
    doc.save(str(path))
    return path


def test_implicit_table_detected_from_column_aligned_text_without_ruling_lines(tmp_path):
    path = _make_pdf_with_borderless_column_grid(tmp_path)

    result = PDFAdapter().extract(path, {})

    tables = result.pages[0].table_candidates
    assert len(tables) == 1
    table = tables[0]
    assert table.detected_as == "implicit_alignment"
    assert table.confidence < 1.0
    assert len(table.rows) == 4
    assert all(len(row) == 3 for row in table.rows)
    assert table.rows[0][0] == "Header"


def test_detect_implicit_tables_option_disables_implicit_detection(tmp_path):
    # 문서 파싱 고도화 Phase 3 config toggle (TextExtractConfig.detect_implicit_tables) —
    # disabled means the aligned text is left as ordinary paragraph text.
    path = _make_pdf_with_borderless_column_grid(tmp_path)

    result = PDFAdapter().extract(path, {"detect_implicit_tables": False})

    assert result.pages[0].table_candidates == []


def test_extract_font_signals_option_disables_line_layout(tmp_path):
    # 문서 파싱 고도화 Phase 3 config toggle (TextExtractConfig.extract_font_signals).
    path = _make_pdf_with_borderless_column_grid(tmp_path)

    result = PDFAdapter().extract(path, {"extract_font_signals": False})

    assert result.metadata["line_layout"] == []


def test_implicit_table_text_is_excluded_from_plain_text_extraction(tmp_path):
    # Same reasoning as ruled tables (_text_excluding_tables): an implicit
    # table's cell text must not also show up as ordinary flowing prose,
    # or downstream structure analysis would double-count it.
    path = _make_pdf_with_borderless_column_grid(tmp_path)

    result = PDFAdapter().extract(path, {})

    plain_text = result.pages[0].text_blocks[0].text if result.pages[0].text_blocks else ""
    assert "RowOne" not in plain_text


class _FakeOutput:
    DICT = "dict"


class _FakePytesseract:
    Output = _FakeOutput()

    def __init__(self, data, text=""):
        self._data = data
        self._text = text
        self.string_config = None

    def image_to_data(self, image, lang, config, output_type):
        return self._data

    def image_to_string(self, image, lang, config):
        self.string_config = config
        return self._text


def test_ocr_page_text_comes_from_image_to_string_not_joined_word_boxes():
    # image_to_data 는 한글을 음절 단위로 쪼개 주므로(이어 붙이면 한 글자 토큰 ~65%) 본문 텍스트는
    # Tesseract 가 직접 만든 image_to_string 결과를 쓰고, data 는 신뢰도 계산에만 쓴다.
    from app.pipeline.adapters.pdf_adapter import _TESSERACT_CONFIG, _ocr_page_with_confidence

    data = {
        "text": ["도", "시", "범", "죄", "", "Second"],
        "conf": ["95", "85", "70", "90", "-1", "80"],
        "block_num": [1] * 6, "par_num": [1] * 6, "line_num": [1, 1, 1, 1, 1, 2],
    }
    fake = _FakePytesseract(data, text="도시 범죄\nSecond\n")

    text, confidence, word_count = _ocr_page_with_confidence(object(), fake)

    assert text == "도시 범죄\nSecond"
    assert fake.string_config == _TESSERACT_CONFIG
    assert word_count == 5
    assert confidence == pytest.approx((95 + 85 + 70 + 90 + 80) / 5 / 100.0)


def test_ocr_page_with_confidence_returns_none_when_no_words_found():
    from app.pipeline.adapters.pdf_adapter import _ocr_page_with_confidence

    data = {
        "text": ["", ""], "conf": ["-1", "-1"],
        "block_num": [1, 1], "par_num": [1, 1], "line_num": [1, 1],
    }

    text, confidence, word_count = _ocr_page_with_confidence(object(), _FakePytesseract(data))

    assert text == ""
    assert confidence is None
    assert word_count == 0


def test_table_marker_numbering_is_global_across_pages_not_reset_per_page(tmp_path):
    # structure_analyze recovers a TABLE node's Document.tables[*]["id"] by
    # parsing the "[표 N]" marker and treating N-1 as a list index (문서 파싱
    # 고도화 Phase 3) — that only works if N is assigned once across the whole
    # document. A per-page-reset counter would print "[표 1]" on every page.
    doc = fitz.open()
    for page_i in range(2):
        page = doc.new_page(width=595, height=842)
        rows = [
            ("Header", "Value", "Status"),
            ("RowOne", "111", "OK"),
            ("RowTwo", "222", "OK"),
            ("RowThree", "333", "FAIL"),
        ]
        for i, (c1, c2, c3) in enumerate(rows):
            y = 100 + i * 20
            page.insert_text((72, y), c1, fontsize=11)
            page.insert_text((220, y), c2, fontsize=11)
            page.insert_text((340, y), c3, fontsize=11)
        for i in range(20):
            page.insert_text(
                (72, 220 + i * 14),
                f"Filler paragraph line page {page_i} to keep text density high.",
                fontsize=11,
            )
    path = tmp_path / "two_page_tables.pdf"
    doc.save(str(path))

    result = PDFAdapter().extract(path, {})

    markers = [
        tb.text.splitlines()[0]
        for page in result.pages
        for tb in page.text_blocks
        if tb.block_type == "table"
    ]
    assert markers == ["[표 1]", "[표 2]"]


def test_ocr_does_not_override_trusted_native_text_even_when_longer(tmp_path, monkeypatch):
    # A sparse-but-legitimate layout (one short paragraph on a big, mostly
    # empty page) can trip the coverage-based OCR trigger even though the
    # native text is already >= _MIN_TRUSTED_NATIVE_CHARS and parsed cleanly —
    # OCR must never win by raw length in that case. Root cause of a real
    # incident: Tesseract's Korean misread of a bulleted layout produced more
    # raw characters than the (correct, shorter) native text and silently
    # replaced it (문서 파싱 고도화 회고, 2026-07-23).
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    native_text = "This is a short but completely valid paragraph of native PDF text."
    page.insert_text((72, 100), native_text, fontsize=11)
    path = tmp_path / "sparse_valid.pdf"
    doc.save(str(path))

    garbled_tokens = ["가", "이", "드", "라", "인"] * 20  # far longer than native_text

    def fake_image_to_data(image, lang, config, output_type):
        return {
            "text": garbled_tokens,
            "conf": ["90"] * len(garbled_tokens),
            "block_num": [1] * len(garbled_tokens),
            "par_num": [1] * len(garbled_tokens),
            "line_num": [1] * len(garbled_tokens),
        }

    monkeypatch.setattr(real_pytesseract, "image_to_data", fake_image_to_data)

    result = PDFAdapter().extract(path, {})

    assert result.pages[0].text_blocks[0].text == native_text
    assert result.pages[0].text_blocks[0].block_type == "paragraph"


def test_implicit_table_not_detected_for_numbered_bulleted_list(tmp_path):
    # A numbered/bulleted list's fixed-indent marker column must not be
    # misdetected as a borderless table's column boundary — this exact
    # pattern (marker + wrapped prose) cropped real paragraph text out of a
    # real 988-page document (문서 파싱 고도화 회고, 2026-07-23).
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    items = [
        ("1.", "사용자 관점의 핵심 UI/UX 문제를 해결할 수 있는 실질적인 방안 제시"),
        ("▪", "VOC, 국민평가, 사용성 및 접근성 진단 등 실제 사용자가 겪는 불편과 어려움을 분석"),
        ("▪", "사용자 데이터 분석 결과를 기반으로 사용성 가이드라인을 제시"),
    ]
    for i, (marker, body) in enumerate(items):
        y = 100 + i * 20
        page.insert_text((72, y), marker, fontsize=11)
        page.insert_text((100, y), body, fontsize=11)
    for i in range(20):
        page.insert_text(
            (72, 200 + i * 14),
            "Filler paragraph line to keep text density high enough.",
            fontsize=11,
        )
    path = tmp_path / "numbered_list.pdf"
    doc.save(str(path))

    result = PDFAdapter().extract(path, {})

    implicit = [t for t in result.pages[0].table_candidates if t.detected_as == "implicit_alignment"]
    assert implicit == []


def test_numbered_list_with_short_labels_is_recognized_as_a_list():
    # Verified against a real 988-page document (문서 파싱 고도화 회고,
    # 2026-07-23): the original heuristic additionally required column 2 to
    # be long prose, which missed numbered section indexes with short labels
    # like this one ("00. 기관 적용 범위 및 항목" / "01. 색상" / "02. 서체" / ...)
    # since "색상"/"서체" never reach the old 15-char prose threshold. Column
    # 2's length must no longer gate detection.
    rows = [
        ["00.", "기관 적용 범위 및 항목"],
        ["01.", "색상"],
        ["02.", "서체"],
        ["03.", "형태"],
        ["04.", "배치"],
        ["05.", "아이콘"],
    ]
    assert _looks_like_list_markers_not_table(rows) is True


def test_font_substituted_bullet_symbol_is_recognized_as_a_marker():
    # A real 988-page document rendered its "▪" bullet as the CJK
    # compatibility character "㏂" in several places (PDF font substitution),
    # which the original fixed-glyph regex never matched (문서 파싱 고도화
    # 회고, 2026-07-23). Any very short column-1 token should count as
    # marker-like regardless of exact character identity.
    rows = [
        ["㏂", "사용성 가이드라인"],
        ["㏂", "접근성 가이드라인"],
        ["㏂", "상호작용 가이드라인"],
        ["㏂", "플랫폼에 대한 고려 사항"],
    ]
    assert _looks_like_list_markers_not_table(rows) is True


def test_plain_prose_is_not_misdetected_as_implicit_table(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    for i in range(5):
        page.insert_text(
            (72, 100 + i * 16),
            "This is an ordinary sentence of flowing prose text.",
            fontsize=11,
        )
    path = tmp_path / "prose.pdf"
    doc.save(str(path))

    result = PDFAdapter().extract(path, {})

    implicit = [t for t in result.pages[0].table_candidates if t.detected_as == "implicit_alignment"]
    assert implicit == []


# ── 일부 칸만 닫힌(선이 불완전한) 표의 셀 밖 텍스트 보존 ─────────────────────────────
# 실제 사례(공고문 "신청 예시별 지원 조건" 표): 머리글 행과 가운데 열만 칸이 닫히고 첫 열·셋째 열 본문에는
# 칸 선이 없다. pdfplumber 는 그 글자를 어떤 셀에도 넣지 못하는데, 표 영역 전체를 본문에서 지워
# 글자가 사라졌다.
def _make_pdf_with_partially_ruled_table(tmp_path: Path) -> Path:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    top, bottom = 100, 300
    left, c1, c2, right = 50, 250, 350, 540
    # 머리글 행은 완전히 닫고, 본문은 가운데 열(c1~c2)만 칸 선을 그린다 — 첫 열과 셋째 열 본문에는
    # 바깥 세로선·가로선·아래 테두리가 없다(실제 공고문 표와 같은 모양).
    page.draw_rect(fitz.Rect(left, top, right, top + 24), width=0.8)
    page.draw_line((c1, top), (c1, bottom), width=0.8)
    page.draw_line((c2, top), (c2, bottom), width=0.8)
    for y in (top + 70, top + 116, top + 162, bottom):
        page.draw_line((c1, y), (c2, y), width=0.8)
    page.insert_text((left + 6, top + 16), "HeaderLeft", fontsize=10)
    page.insert_text((c1 + 6, top + 16), "Limit", fontsize=10)
    page.insert_text((c2 + 6, top + 16), "Target", fontsize=10)
    page.insert_text((left + 6, top + 50), "LeftBodyAlpha zeta one", fontsize=10)
    page.insert_text((left + 6, top + 96), "LeftBodyBeta zeta two", fontsize=10)
    page.insert_text((c1 + 6, top + 50), "Max05", fontsize=10)
    page.insert_text((c1 + 6, top + 96), "Max20", fontsize=10)
    page.insert_text((c2 + 6, top + 50), "RightBodyGamma", fontsize=10)
    for i in range(14):
        page.insert_text((72, 340 + i * 14), f"Filler paragraph line {i} to keep the text density high.", fontsize=11)
    path = tmp_path / "partial_table.pdf"
    doc.save(str(path))
    return path


def _all_page_text(result) -> str:
    return "\n".join(tb.text for page in result.pages for tb in page.text_blocks)


def test_text_outside_closed_cells_of_a_ruled_table_is_not_lost(tmp_path):
    path = _make_pdf_with_partially_ruled_table(tmp_path)

    text = _all_page_text(PDFAdapter().extract(path, {}))

    for expected in ("LeftBodyAlpha", "LeftBodyBeta", "RightBodyGamma", "Max05", "Max20"):
        assert expected in text, f"{expected} 가 추출 결과에서 사라졌다"


def test_cell_text_is_not_duplicated_in_body_text_and_table_block(tmp_path):
    path = _make_pdf_with_partially_ruled_table(tmp_path)

    text = _all_page_text(PDFAdapter().extract(path, {}))

    # 칸에 들어간 글자는 표 블록에만, 칸 밖 글자는 본문에만 — 어느 쪽이든 한 번만 나와야 한다
    assert text.count("Max05") == 1
    assert text.count("LeftBodyAlpha") == 1


def test_extract_reports_embedded_title_property(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Body text of the document", fontsize=12)
    doc.set_metadata({"title": "AI Servor 기능 소개서"})
    path = tmp_path / "titled.pdf"
    doc.save(path)
    doc.close()

    result = PDFAdapter().extract(path, {})

    assert result.metadata["document_title"] == "AI Servor 기능 소개서"


def test_extract_embedded_title_is_none_when_absent(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Body text of the document", fontsize=12)
    path = tmp_path / "untitled.pdf"
    doc.save(path)
    doc.close()

    result = PDFAdapter().extract(path, {})

    assert not result.metadata["document_title"]
