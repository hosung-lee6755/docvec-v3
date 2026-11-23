"""요약 입력의 금액 단위 풀어 쓰기: 3B 모델이 "7,500[천원]"을 "7500원"으로 옮기던 문제(2026-11-23)."""
import pytest

from app.pipeline.money_units import spell_out_money_units


@pytest.mark.parametrize("source, expected", [
    ("연간 매출액 9,000 [백만원]", "연간 매출액 90억 원"),
    ("지원 한도는 300백만원, 추가", "지원 한도는 3억 원, 추가"),
    ("추정가격이 8천만원을 초과", "추정가격이 8,000만 원을 초과"),
    ("사업비 7,500천원", "사업비 750만 원"),
    ("비용 86.32 [백만원]", "비용 8,632만 원"),
    ("12,345,678 [천원]", "123억 4,567만 8,000원"),
    ("단가 0.5 (천원)", "단가 500원"),
])
def test_inline_amounts_are_spelled_out_in_won(source, expected):
    assert spell_out_money_units(source) == expected


@pytest.mark.parametrize("source", [
    "계약금액이 100억원 이상",       # 억원과 만원은 모델이 그대로 옮긴다
    "1인당 50만원 지원",
    "용량 [kW] 37",
    "천원 단위로 적는다",             # 숫자가 없다
])
def test_units_the_model_already_copies_are_left_alone(source):
    assert spell_out_money_units(source) == source


def test_table_column_with_a_unit_header_converts_each_numeric_cell():
    source = (
        "| 개선내용 | 절감금액 [백만원/년] | 투자비 [백만원] | 회수 기간 [년] |\n"
        "|---|---|---|---|\n"
        "| 인버터 설치 | 2.34 | 7.50 | 3.21 |\n"
        "| 합계 | - | 1,000 | 비고 |"
    )

    assert spell_out_money_units(source) == (
        "| 개선내용 | 절감금액 [원/년] | 투자비 [원] | 회수 기간 [년] |\n"
        "|---|---|---|---|\n"
        "| 인버터 설치 | 234만 원 | 750만 원 | 3.21 |\n"
        "| 합계 | - | 10억 원 | 비고 |"
    )


def test_parenthesised_unit_header_is_converted_too():
    source = "| 품목 | 금 액 / (천원) |\n|---|---|\n| 트랙터 | 45,000 |"

    assert spell_out_money_units(source) == "| 품목 | 금 액 / (원) |\n|---|---|\n| 트랙터 | 4,500만 원 |"


def test_unit_caption_applies_to_every_numeric_cell_of_the_next_table():
    source = (
        "(단위 : 백만원)\n"
        "| 구분 | 2023 | 2024 |\n"
        "|---|---|---|\n"
        "| 국비 | 150 | 1,200.5 |\n"
        "\n"
        "| 구분 | 2023 |\n"
        "|---|---|\n"
        "| 인원 | 3 |"
    )

    assert spell_out_money_units(source) == (
        "(단위 : 원)\n"
        "| 구분 | 2023 | 2024 |\n"
        "|---|---|---|\n"
        "| 국비 | 1억 5,000만 원 | 12억 50만 원 |\n"
        "\n"
        "| 구분 | 2023 |\n"
        "|---|---|\n"
        "| 인원 | 3 |"
    )


def test_caption_reaches_a_table_without_outer_bars_past_its_title():
    # 2026년 사업시행지침(HWP) 실측: 안내와 표 사이에 빈 줄과 표 번호가 끼고, 표에 바깥 "|"가 없다
    source = "(단위 : 백만원)\n\n[표 6]\n구 분 | 2015년 | 2016년\n합 계 | 136,291 | 119,608"

    assert spell_out_money_units(source) == (
        "(단위 : 원)\n\n[표 6]\n구 분 | 2015년 | 2016년\n합 계 | 1,362억 9,100만 원 | 1,196억 800만 원"
    )


def test_caption_without_a_following_table_is_not_rewritten():
    # 숫자를 바꾸지 못했는데 안내만 "원"이 되면 오히려 틀린 정보가 된다
    source = "(단위 : 백만원)\n설명 문단 하나\n설명 문단 둘\n설명 문단 셋\n| 구분 | 금액 |\n|---|---|\n| 계 | 5 |"

    assert spell_out_money_units(source) == source


def test_a_header_row_repeated_inside_a_block_switches_the_column_units():
    # 에너지 진단 보고서 실측: 두 표가 빈 줄 없이 붙어 둘째 표의 머리글이 블록 중간에 있다
    source = (
        "| 진단전 [toe/년] | 절감률 [%] |\n"
        "|---|---|\n"
        "| 682.60 | 1.71 |\n"
        "| 개선내용 | 절감액 (천원/년) | 투자비 (천원) |\n"
        "| 공기압축기 교체 | 9,789 | 8,000 |"
    )

    assert spell_out_money_units(source) == (
        "| 진단전 [toe/년] | 절감률 [%] |\n"
        "|---|---|\n"
        "| 682.60 | 1.71 |\n"
        "| 개선내용 | 절감액 (원/년) | 투자비 (원) |\n"
        "| 공기압축기 교체 | 978만 9,000원 | 800만 원 |"
    )


def test_units_stay_when_no_number_in_the_column_could_be_converted():
    # 빈 서식(입찰 실적표 등)은 숫자 칸이 없으므로 단위 표기도 원문 그대로 둔다
    source = "(단위 : 천원)\n| 용역명 | 계약금액 (백만원) |\n|---|---|\n| | |"

    assert spell_out_money_units(source) == source


def test_caption_with_several_units_is_ambiguous_and_left_alone():
    source = "(단위 : ha, 기, 백만원)\n| 구분 | 면적 |\n|---|---|\n| 계 | 120 |"

    assert spell_out_money_units(source) == source
