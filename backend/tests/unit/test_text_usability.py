from app.pipeline.blocks.text_usability import single_char_token_ratio, usable_char_count


def test_markup_and_whitespace_do_not_count_as_usable_text():
    table_only = "| --- | --- |\n| | |\n| --- | --- |\n## \n"
    assert usable_char_count(table_only) == 0


def test_words_in_table_cells_and_paragraphs_count():
    assert usable_char_count("| 항목 | 값 |\n| 예산 | 100 |") == len("항목값예산100")


def test_spaced_out_hangul_is_detected_as_ocr_scatter():
    scattered = "서 울 시 도 시 범 죄 취 약 지 분 석"
    assert single_char_token_ratio(scattered) == 1.0


def test_normal_korean_text_has_low_scatter():
    assert single_char_token_ratio("서울시 도시 범죄 취약지 분석 및 억제 방안 연구") < 0.15


def test_empty_text_has_zero_scatter():
    assert single_char_token_ratio("") == 0.0
