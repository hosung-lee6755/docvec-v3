"""Docling 글과 원본 글자 층(pdfplumber) 중 띄어쓰기가 덜 깨진 쪽을 고른다(2026-11-20 감사).

KR S-03010 선로전환기 PDF 에서 Docling 이 "첨 단간 : 텅레 일의 작 동을"처럼 낱말 중간을 띄웠고,
Pub120bk 에서는 "V oluntary"처럼 영어 첫 글자를 떼었다. 사례집 PDF 처럼 원본 글자 층이 오히려
낱말을 붙여 읽는 경우도 있어, 글자가 같을 때만 덜 깨진 쪽을 고른다."""
import fitz

from app.pipeline.adapters.native_spacing import (
    NativeRegionReader,
    choose_spacing,
    prefer_native_on_duplicate_layer,
    restore_marker,
    spacing_score,
)


def test_broken_korean_spacing_scores_worse_than_natural_spacing():
    assert spacing_score("첨 단간 : 텅레 일의 작 동을 쇄정간에 전 달 하기 위해") > spacing_score(
        "첨단간 : 텅레일의 작동을 쇄정간에 전달하기 위해"
    )


def test_merged_korean_words_score_worse_than_natural_spacing():
    assert spacing_score("효율적인개인하수처리시설점검대상선정") > spacing_score("효율적인 개인하수처리시설 점검대상 선정")


def test_split_first_letter_of_english_word_scores_worse():
    assert spacing_score("operating in the V oluntary Community") > spacing_score("operating in the Voluntary Community")


def test_native_text_wins_when_docling_breaks_words():
    docling = "첨 단간 : 텅레 일의 작 동을 쇄정간에 전 달 하기 위해"
    native = "첨단간 : 텅레일의 작동을 쇄정간에 전달하기 위해"

    assert choose_spacing(docling, native) == native


def test_native_lines_are_joined_into_one_paragraph():
    docling = "Vessels are advised to remain vigilant in the V oluntary area."
    native = "Vessels are advised to remain\nvigilant in the Voluntary area."

    assert choose_spacing(docling, native) == "Vessels are advised to remain vigilant in the Voluntary area."


def test_docling_text_is_kept_when_native_text_merges_words():
    docling = "효율적인 개인하수처리시설 점검대상 선정"

    assert choose_spacing(docling, "효율적인개인하수처리시설점검대상선정") == docling


def test_docling_text_is_kept_when_the_letters_differ():
    # 영역이 어긋나 옆 단의 글이 섞이면 글자가 달라진다. 그때는 손대지 않는다
    docling = "첨 단간 : 텅레 일의 작 동을"

    assert choose_spacing(docling, "첨단간 : 텅레일의 작동을 쇄정간에 (옆 단)") == docling
    assert choose_spacing(docling, "") == docling


def test_native_text_with_a_list_number_docling_dropped_is_used_when_it_wins():
    docling = "첨 단간 : 텅레 일의 작 동을"

    assert choose_spacing(docling, "(8) 첨단간 : 텅레일의 작동을") == "(8) 첨단간 : 텅레일의 작동을"


def test_native_text_wins_when_docling_moves_numbering_punctuation():
    # 세원화성 에너지진단보고서(2026-11-20): 기호와 숫자 글꼴이 달라 Docling 이 마침표·괄호를 뒤로 옮긴다
    assert choose_spacing("가 에너지원별 사용량 .", "가. 에너지원별 사용량") == "가. 에너지원별 사용량"
    assert choose_spacing("표 공기압축기 운전 데이터 [ 1.3]", "[표 1.3] 공기압축기 운전 데이터") == (
        "[표 1.3] 공기압축기 운전 데이터"
    )


def test_native_text_wins_when_docling_drops_numbers_and_symbols():
    docling = "스크류 타입 공기압 축기 대 가 가동되고 있으며"
    native = "1) 스크류 타입 공기압\n축기 2대(75HP/1, 30HP/1)가 가동되고 있으며"

    assert choose_spacing(docling, native) == "1) 스크류 타입 공기압 축기 2대(75HP/1, 30HP/1)가 가동되고 있으며"


def test_docling_text_is_kept_when_native_has_extra_korean_or_another_order():
    docling = "가 에너지원별 사용량 ."

    # 옆 글이 섞여 한글이 늘었다
    assert choose_spacing(docling, "가. 에너지원별 사용량 단위 톤") == docling
    # 한글 순서가 다르다(여러 단이 섞인 영역)
    assert choose_spacing(docling, "사용량 가. 에너지원별") == docling
    # Docling 에만 있는 글자가 있다
    assert choose_spacing("가 에너지원별 사용량 (주)", "가. 에너지원별 사용량") == "가 에너지원별 사용량 (주)"


def test_formula_glyphs_in_private_use_area_block_the_symbol_rule():
    # 기계설비 매뉴얼: 수식 글꼴의 아래첨자를 원본 글자 층이 줄 끝으로 옮긴다
    docling = "두 연결점에 대하여  는 다음과 같이 계산한 다."

    assert choose_spacing(docling, "두 연결점에 대하여 는 다음과 같이 계산한  다.") == docling


def test_subscript_digits_moved_away_by_native_text_block_the_symbol_rule():
    # 원본 글자 층은 아래첨자 숫자를 줄 뒤로 보낸다("CO2" → "CO … 2")
    assert choose_spacing("CO2 농도 상한치", "2. CO 농도 상한치 2") == "CO2 농도 상한치"


def test_english_text_is_not_repaired_by_symbol_rule():
    assert choose_spacing("Total cost .", "Total cost 2. 3") == "Total cost ."


def test_characters_docling_normalized_are_restored_from_the_native_text():
    # 2026-11-26 기호 대조: Docling 은 "•" 를 "·" 로, 둥근 따옴표를 곧은 따옴표로 바꿔 원문 글자가 RAG 본문에서 바뀌었다
    assert choose_spacing("· 데이터 기반 예측을 통해", "• 데이터 기반 예측을 통해") == "• 데이터 기반 예측을 통해"
    assert choose_spacing("· 데이터 기반 예측을 통해", "•데이터기반예측을통해") == "• 데이터 기반 예측을 통해"
    assert choose_spacing('the "Voluntary" area\'s 1/2', "the “Voluntary” area’s 1⁄2") == "the “Voluntary” area’s 1⁄2"


def test_symbols_docling_parse_rewrote_are_restored_but_letters_are_not():
    # Pub120bk: 원본 "Alert—Provides" 가 "Alert-Provides" 로 저장되었다(docling-parse 가 대시를 바꾼다)
    assert choose_spacing("1. U.S. Maritime Alert-Provides basic", "1. U.S. Maritime Alert—Provides basic") == (
        "1. U.S. Maritime Alert—Provides basic"
    )
    # 문자·숫자가 다르거나, 원본이 사용자 정의 영역 글자면 Docling 글을 둔다
    assert choose_spacing("Alert-Provides 2024", "Alert—Provides 2025") == "Alert-Provides 2024"
    assert choose_spacing("- 데이터 기반", " 데이터 기반") == "- 데이터 기반"


def test_characters_are_restored_after_a_list_marker_docling_dropped():
    # 원본 앞의 목록 기호는 Docling 글에 없으므로, 그 뒤 글자만 원본 글자로 되돌린다
    assert choose_spacing('"효율" 증대', '1. “효율”증대') == "“효율” 증대"


def test_list_marker_is_written_as_the_original_glyph():
    assert restore_marker("·", "• 데이터 기반") == "•"
    assert restore_marker("1.", "1. 사업 개요") == "1."
    assert restore_marker("·", "") == "·"


def _pdf_with_text(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=300, height=200)
    page.insert_text((20, 50), "Voluntary reporting area", fontsize=11)
    page.insert_text((20, 150), "Footer line", fontsize=11)
    path = tmp_path / "region.pdf"
    doc.save(str(path))
    return path


def test_region_reader_reads_a_glyph_drawn_twice_at_the_same_spot_once(tmp_path):
    # 2026-11-27: 한글에서 내보낸 휴직규정 PDF 는 한 겹에 한글만, 다른 겹에 숫자까지 같은 자리에 그렸다.
    # 원본 글이 "제제1조조"가 되어 Docling 이 옮긴 숫자("제 조 1")를 바로잡지 못했다
    doc = fitz.open()
    page = doc.new_page(width=300, height=200)
    for x, ch in ((10, "A"), (28, "B")):
        page.insert_text((x, 50), ch, fontsize=12)
    for x, ch in ((10, "A"), (19, "1"), (28, "B")):
        page.insert_text((x, 50), ch, fontsize=12)
    path = tmp_path / "double.pdf"
    doc.save(path)
    reader = NativeRegionReader(path, [])

    text = reader.read(1, (0.0, 30.0, 300.0, 60.0))
    reader.close()

    assert text.replace(" ", "") == "A1B"


def test_page_drawn_in_two_layers_is_flagged_and_a_single_layer_page_is_not(tmp_path):
    doc = fitz.open()
    doubled = doc.new_page(width=300, height=200)
    for _ in range(2):
        doubled.insert_text((10, 50), "Article one", fontsize=12)
    single = doc.new_page(width=300, height=200)  # 새 쪽을 만들면 앞 쪽 객체를 다시 쓸 수 없어 쪽마다 바로 그린다
    single.insert_text((10, 50), "Article one", fontsize=12)
    path = tmp_path / "layers.pdf"
    doc.save(path)
    reader = NativeRegionReader(path, [])

    assert reader.has_duplicate_layer(1) is True
    assert reader.has_duplicate_layer(2) is False
    reader.close()


def test_native_text_is_used_on_a_two_layer_page_when_it_holds_all_docling_hangul():
    # 휴직규정 제2조: Docling 은 한 겹을 읽어 숫자와 괄호를 옮기고 둥근 따옴표를 곧은 따옴표로 바꿨다
    docling = "제 조 적용범위 2 ( ) 이 규정은 본국직원 이하 직원 이라 한다 에게 적용한다 다만 ( ' ' ) . ,"
    native = "제2조(적용범위) 이 규정은 본국직원(이하 “직원”이라 한다)에게 적용한다. 다만,"

    assert prefer_native_on_duplicate_layer(docling, native) == native
    # 원본 글이 Docling 한글을 다 담지 못하면(다른 영역을 읽었으면) Docling 글을 그대로 둔다
    assert prefer_native_on_duplicate_layer(docling, "제2조(적용범위)") == docling


def test_region_reader_reads_only_the_bbox_in_either_origin(tmp_path):
    path = _pdf_with_text(tmp_path)
    warnings: list[str] = []
    reader = NativeRegionReader(path, warnings)

    top_left = reader.read(1, (10.0, 35.0, 290.0, 60.0))
    bottom_left = reader.read(1, (10.0, 200 - 35.0, 290.0, 200 - 60.0))
    reader.close()

    assert top_left == "Voluntary reporting area"
    assert bottom_left == "Voluntary reporting area"
    assert warnings == []


def test_region_reader_returns_empty_text_for_missing_page_or_bbox(tmp_path):
    reader = NativeRegionReader(_pdf_with_text(tmp_path), [])

    assert reader.read(5, (0.0, 0.0, 10.0, 10.0)) == ""
    assert reader.read(1, None) == ""
    reader.close()


def test_region_reader_reports_once_and_gives_up_on_a_broken_file(tmp_path):
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"not a pdf")
    warnings: list[str] = []
    reader = NativeRegionReader(broken, warnings)

    assert reader.read(1, (0.0, 0.0, 10.0, 10.0)) == ""
    assert reader.read(1, (0.0, 0.0, 10.0, 10.0)) == ""
    assert len(warnings) == 1


def test_symbol_font_codes_on_a_page_are_read_by_the_font_they_are_drawn_with():
    # 법령심사 PDF 는 " 법제처의 업무" 를 Wingdings 로, 세원화성 PDF 는 " 고효율변압기" 를 이름을 가린 내장
    # 글꼴(CIDFont+F4, 실제 이름 Wingdings)로 그렸다. 파싱 본문에는 코드가 남아 빈칸으로 보였다(2026-11-26)
    from app.pipeline.adapters.native_spacing import page_symbol_chars

    real_names = {"CIDFont+F4": "Wingdings Regular", "CIDFont+F2": "Gulim Regular"}
    spans = [("Wingdings", ""), ("CIDFont+F4", ""), ("CIDFont+F2", "법제처"), ("SymbolMT", "")]

    assert page_symbol_chars(spans, real_names.get) == {"": "●", "": "•", "": "✓", "": "μ"}


def test_symbol_codes_drawn_with_an_unknown_font_on_the_page_are_left_alone():
    # 같은 코드가 표를 모르는 글꼴(아이콘 글꼴 Type3, 수식 글꼴)에도 쓰였으면 어느 글자인지 모르므로 바꾸지 않는다
    from app.pipeline.adapters.native_spacing import page_symbol_chars

    spans = [("Wingdings", ""), ("Type3", ""), ("Type3", ""), ("HCRDotum", "")]

    assert page_symbol_chars(spans, lambda name: None) == {}


def test_text_read_inside_a_picture_gets_the_symbol_font_glyphs(monkeypatch):
    # 그림 영역 안 글은 NativeRegionReader 를 거치지 않아 "" 가 청크에 빈칸으로 남았다(2026-11-26)
    from app.pipeline.adapters import native_spacing

    class _Page:
        def get_fonts(self, full=True):
            return []

    monkeypatch.setattr(native_spacing, "_page_chars", lambda page: [
        {"font": "Wingdings", "text": ""}, {"font": "Malgun Gothic", "text": "법"},
    ])

    assert native_spacing.with_page_symbols(None, _Page(), " 법제처의 업무") == "● 법제처의 업무"
    assert native_spacing.with_page_symbols(None, _Page(), "기호 없는 글") == "기호 없는 글"


def test_pdf_symbol_pages_maps_codes_for_the_pdfplumber_path(monkeypatch, tmp_path):
    # pdf_adapter(pdfplumber) 경로에는 바꾸는 단계가 없어 법령심사 PDF 의 "●" 가 코드로 남았다(2026-11-26)
    import fitz

    from app.pipeline.adapters import native_spacing

    path = tmp_path / "one.pdf"
    with fitz.open() as pdf:
        pdf.new_page()
        pdf.save(str(path))
    monkeypatch.setattr(native_spacing, "page_symbol_map", lambda doc, page, cache: {"": "●"})
    warnings: list[str] = []
    pages = native_spacing.PdfSymbolPages(path, warnings)

    symbols = pages.for_page(1)
    pages.close()

    assert native_spacing.with_symbol_map(" 법제처", symbols) == "● 법제처"
    assert native_spacing.with_symbol_map("그대로", {}) == "그대로" and warnings == []


def test_native_text_replaces_phantom_symbols_docling_misread():
    # 한컴 글꼴 PDF 에서 Docling 이 띄어쓰기를 "'"로, 따옴표를 NKo 문자로 읽었다(임금피크제시행내규, 2026-11-27)
    docling = "제1조(목적) 이' 시행내규는' 임금피크제' 대상' 직원의' 인사 ߫ 임금피크제 '߬ 란"
    native = "제1조(목적) 이 시행내규는 임금피크제 대상 직원의 인사 “임금피크제” 란"

    assert choose_spacing(docling, native) == native


def test_one_extra_symbol_alone_does_not_replace_docling_text():
    docling = "이 규정은 시행한다'"
    native = "이 규정은 시행한다"

    assert choose_spacing(docling, native) in (docling, native)  # 한 개는 판정 기준(3개) 밖이다
    from app.pipeline.adapters import native_spacing

    assert not native_spacing._has_phantom_symbols(docling, native)


def test_region_read_takes_characters_whose_centre_is_inside(tmp_path):
    # Docling 영역이 글자 윗변보다 몇 pt 아래에서 시작해도 그 줄의 글자를 읽는다(임금피크제시행내규, 2026-11-27)
    from app.pipeline.adapters.native_spacing import NativeRegionReader

    doc = fitz.open()
    page = doc.new_page(width=300, height=200)
    page.insert_text((20, 50), "ABC DEF", fontsize=12)
    path = tmp_path / "centre.pdf"
    doc.save(path)
    reader = NativeRegionReader(path, [])

    # 글자 윗변(약 40.4)보다 5pt 아래(45)에서 시작하는 영역
    text = reader.read(1, (15.0, 45.0, 200.0, 56.0))
    reader.close()

    assert "ABC" in text and "DEF" in text
