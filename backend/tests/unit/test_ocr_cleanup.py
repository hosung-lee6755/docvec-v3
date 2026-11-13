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
