"""그림 OCR 잡음 거르기와 % 오인식 보정(2026-11-13 전처리 성능 검토 3·5절)."""
from app.pipeline import ocr_cleanup as oc
from app.pipeline.adapters.base import RawPage, RawTableCandidate, RawTextBlock


# ---------------------------------------------------------------- 그림 OCR


def test_figure_text_keeps_meaningful_lines_and_drops_noise_lines():
    text = "cee oe /종ㅣ\n선형 회귀 기반 모델\nRidge Lasso\n\nZhi\nRMSE 46,048,198"

    kept = oc.figure_text_for_body(text)

    assert kept.splitlines() == ["선형 회귀 기반 모델", "Ridge Lasso", "RMSE 46,048,198"]


def test_figure_text_made_only_of_noise_is_dropped_entirely():
    for noise in ["Zhi\n\nee", "~  earnnie\n+ aR", "is ee\nieee 3\nioe\n\nes\n\nct", "wR OR AR", "© wus"]:
        assert oc.figure_text_for_body(noise) == "", noise


def test_figure_text_with_too_little_left_is_dropped():
    assert oc.figure_text_for_body("개요") == ""


def test_figure_text_of_a_clean_chart_is_kept_as_is():
    text = "상수도업종분포\n업종별상수도사용량(단위: 만(㎥))\n69,734\n19,987\n가정용\n일반용"

    assert oc.figure_text_for_body(text) == text


# ---------------------------------------------------------------- % 오인식


def test_percent_misreads_in_a_rate_table_are_restored():
    rows = [
        ["평균운임차이비율", "0.909"],
        ["운임 일치울", "87.009"],
        ["1만원 이내 일치울", "94.3096"],
        ["", "98.4096"],
    ]

    fixed = oc.fix_percent_in_rows(rows)

    assert [r[1] for r in fixed] == ["0.90%", "87.00%", "94.30%", "98.40%"]
    assert rows[1][1] == "87.009"  # 원본 행은 바꾸지 않는다


def test_p_values_and_real_three_decimal_numbers_are_left_alone():
    lines = [
        "0.005**        0.001***         0.209          0.437          0.984",
        "               0.0494                 0.116                 0.669",
        "t-test2t     0.062       0.019*       0.714        0.600       0.623",
        "[예시] 1,000(MWh) x 0.229(toe/MWh) = 229(toe)",
    ]
    for line in lines:
        assert oc.fix_percent_misreads(line) == line


def test_three_decimal_rates_that_are_not_all_suspicious_are_left_alone():
    # 적중률을 소수로 적은 표: 끝자리가 9가 아닌 값이 섞여 있으면 진짜 소수로 본다
    text = "적중률 | 0.909\n재현율 | 0.875\n정밀도 | 0.912"

    assert oc.fix_percent_misreads(text) == text


def test_suspicious_numbers_without_rate_context_are_left_alone():
    assert oc.fix_percent_misreads("평균 87.009 | 94.3096") == "평균 87.009 | 94.3096"


def test_a_single_suspicious_number_is_left_alone():
    assert oc.fix_percent_misreads("운임 일치율은 87.009로 나타났다") == "운임 일치율은 87.009로 나타났다"


def test_exchange_rates_are_not_percentages():
    text = "원/달러 환율 | 1.009 | 1.019"

    assert oc.fix_percent_misreads(text) == text


def test_a_table_that_already_shows_real_percent_signs_is_left_alone():
    # % 열이 제대로 읽힌 표의 p값(0.009, 0.019)은 진짜 소수다
    text = "구분 | 비율 | p\nA | 12.5% | 0.009\nB | 30.1% | 0.019"

    assert oc.fix_percent_misreads(text) == text


def test_values_that_would_exceed_one_hundred_percent_are_left_alone():
    text = "증가율 | 187.009 | 294.3096"

    assert oc.fix_percent_misreads(text) == text


# ---------------------------------------------------------------- 문서 전체 적용


def _page(blocks, tables):
    return RawPage(page_number=1, width=100, height=100, text_blocks=blocks,
                   table_candidates=tables, image_regions=[])


def test_fix_percent_in_pages_fixes_table_blocks_and_table_candidates():
    table_text = "[표 1]\n운임 일치울 | 87.009\n1만원 이내 일치울 | 94.3096"
    page = _page(
        [
            RawTextBlock(text="본문입니다.", page_number=1),
            RawTextBlock(text=table_text, page_number=1, block_type="table"),
        ],
        [RawTableCandidate(page_number=1, rows=[["운임 일치울", "87.009"], ["1만원 이내 일치울", "94.3096"]])],
    )

    count = oc.fix_percent_in_pages([page])

    assert count == 2
    assert page.text_blocks[1].text == "[표 1]\n운임 일치울 | 87.00%\n1만원 이내 일치울 | 94.30%"
    assert page.text_blocks[0].text == "본문입니다."
    assert page.table_candidates[0].rows == [["운임 일치울", "87.00%"], ["1만원 이내 일치울", "94.30%"]]


# ---------------------------------------------------------------- 그림 OCR 줄 신뢰도(2026-11-23)


def test_low_confidence_lines_are_dropped_from_figure_text():
    # 정민산업 에너지진단보고서 그림: "wise waso22 45"(신뢰도 5.7)는 낱말·숫자 비율 기준은 통과했다
    text = "Air COMP. 계통도\n\nwise waso22 45\nwilt 0\"\n37[kW]"

    kept = oc.drop_low_confidence_lines(text, [91.0, 5.7, 32.5, 88.0])

    assert kept == "Air COMP. 계통도\n\n37[kW]"


def test_figure_text_is_kept_whole_when_lines_cannot_be_aligned():
    text = "첫 줄\n둘째 줄"

    assert oc.drop_low_confidence_lines(text, [10.0]) == text


def test_figure_text_that_is_mostly_symbols_is_dropped():
    # 심야버스 분석 요약본 그림 1(2026-11-25): ">|:    >| aevus"가 본문과 청크에 들어갔다
    assert oc.figure_text_for_body(">|:    >| aevus") == ""


_NATIVE = (
    "빅데이터 기반 심야버스 노선을 분석하였다. 심야버스 2개 노선을 시범 운행하였다. 빅데이터를 분석하였다. "
    "유동인구 분포 패턴과 택시 분포 패턴을 비교하였다."
)


def test_ocr_words_one_letter_off_a_word_of_the_same_document_are_corrected():
    # 쪽 제목이 그림 글자라 OCR로 읽은 부분만 "넥데이터", "심아버스"로 틀렸다. 같은 문서 글자 층에는 바른 낱말이 있다
    vocabulary = oc.DocumentVocabulary(_NATIVE)

    assert vocabulary.correct("넥데이터 기반 심아버스 노선 수립올 위한 분석") == "빅데이터 기반 심야버스 노선 수립을 위한 분석"
    assert vocabulary.correct("수요에 영향올 미칠 수 있는") == "수요에 영향을 미칠 수 있는"


def test_words_found_in_the_text_layer_or_without_a_unique_match_are_left_alone():
    vocabulary = oc.DocumentVocabulary(_NATIVE + " 분석가 분석자")

    # 글자 층에 그대로 있는 낱말, 짧은 낱말, 후보가 둘인 낱말(분석가/분석자), 한 번만 나온 후보는 바꾸지 않는다
    assert vocabulary.correct("심야버스 패련 분석사 노선도") == "심야버스 패련 분석사 노선도"
    assert vocabulary.correct("서울 위한 겨울 동안") == "서울 위한 겨울 동안"


def test_vocabulary_correction_reaches_text_blocks_and_table_cells():
    page = RawPage(
        page_number=1, width=1, height=1,
        text_blocks=[RawTextBlock(text="넥데이터 분석", page_number=1)],
        table_candidates=[RawTableCandidate(page_number=1, rows=[["심아버스", "1"]])],
        image_regions=[],
    )

    fixed = oc.correct_pages_with_vocabulary([page], _NATIVE)

    assert fixed == 2
    assert page.text_blocks[0].text == "빅데이터 분석"
    assert page.table_candidates[0].rows == [["심야버스", "1"]]


def test_real_words_one_letter_off_a_document_word_are_not_rewritten():
    # 전체 PDF 시험 적용(2026-11-25): 그림 OCR 의 "가속도", "지원내역", "적용기술"은 바른 낱말인데 문서에 있는
    # "휠속도", "지원내용", "적용기준"으로 바뀌었다. 형태소 분석 점수가 후보보다 크게 나쁠 때만 바꾼다
    native = "휠속도 휠속도 지원내용 지원내용 적용기준 적용기준 모니터링 모니터링"
    vocabulary = oc.DocumentVocabulary(native)

    assert vocabulary.correct("가속도 지원내역 적용기술 모니터림") == "가속도 지원내역 적용기술 모니터링"
