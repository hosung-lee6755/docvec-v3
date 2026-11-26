"""Docling 글과 원본 글자 층(pdfplumber) 중 띄어쓰기가 덜 깨진 쪽을 고른다(2026-11-20 감사).

KR S-03010 선로전환기 PDF 에서 Docling 이 "첨 단간 : 텅레 일의 작 동을"처럼 낱말 중간을 띄웠고,
Pub120bk 에서는 "V oluntary"처럼 영어 첫 글자를 떼었다. 사례집 PDF 처럼 원본 글자 층이 오히려
낱말을 붙여 읽는 경우도 있어, 글자가 같을 때만 덜 깨진 쪽을 고른다."""
import fitz

from app.pipeline.adapters.native_spacing import NativeRegionReader, choose_spacing, restore_marker, spacing_score


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
