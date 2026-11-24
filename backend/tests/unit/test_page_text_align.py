from app.services.page_text_align import split_text_by_pages

BODY = (
    "제1장 총칙\n이 지침은 조사료 생산기반 확충 사업의 시행에 필요한 사항을 정한다.\n"
    "제2장 사업 대상\n사업 대상은 축산 농가와 생산자 단체로 한다.\n"
    "제3장 지원 기준\n지원 기준은 사업량과 단가에 따른다.\n"
)


def test_splits_parsed_text_at_each_preview_page_start():
    pages = [
        "제1장 총칙 이 지침은 조사료 생산기반 확충 사업의",
        "제2장 사업 대상 사업 대상은 축산 농가와 생산자 단체로 한다.",
        "제3장 지원 기준 지원 기준은 사업량과 단가에 따른다.",
    ]

    pieces = split_text_by_pages(BODY, pages)

    assert pieces is not None and len(pieces) == 3
    assert pieces[0].startswith("제1장") and pieces[1].startswith("제2장") and pieces[2].startswith("제3장")
    assert "".join(pieces) == BODY


def test_skips_a_running_header_that_cleaning_removed():
    # 미리보기 쪽 머리에 "사업시행지침 - 2 -" 같은 머리말이 있어도 그 뒤 글로 경계를 찾는다
    pages = ["제1장 총칙", "사업시행지침 2021년도 개정판 제2장 사업 대상 사업 대상은 축산 농가와", "제3장 지원 기준 지원 기준은"]

    pieces = split_text_by_pages(BODY, pages)

    assert pieces is not None and pieces[1].startswith("제2장")


def test_page_whose_start_is_missing_is_empty_and_its_text_stays_on_the_previous_page():
    pages = ["제1장 총칙", "그림만 있는 쪽 캡션은 본문에 없습니다", "제2장 사업 대상 사업 대상은 축산", "제3장 지원 기준 지원 기준은"]

    pieces = split_text_by_pages(BODY, pages)

    assert pieces is not None
    assert pieces[1] == "" and pieces[0].startswith("제1장") and pieces[2].startswith("제2장")
    assert "".join(pieces) == BODY


def test_returns_none_when_most_pages_cannot_be_found_or_there_is_one_page():
    unrelated = ["가나다라마바사아자차카타파하 첫쪽", "전혀 다른 문서의 둘째 쪽 글입니다 여기", "또 다른 셋째 쪽 글입니다 여기에"]

    assert split_text_by_pages(BODY, unrelated) is None
    assert split_text_by_pages(BODY, ["한 쪽뿐"]) is None
    assert split_text_by_pages("", ["가", "나"]) is None


def test_table_label_that_heads_a_page_moves_with_its_table():
    # 파싱 본문은 표 앞에 "[표 N]" 머리표를 붙이지만 미리보기 쪽은 표 칸 글로 시작한다. 머리표가 앞 쪽 끝에 남지
    # 않고 표와 같은 쪽으로 가야 한다(NS-AM 3쪽 끝에 "[표 4]"가 붙었다, 2026-11-23)
    body = (
        "[표 3]\n절차서 2 | 검사번호 | KR-I-NSAM-02.01 | 공급확인서 및 성적서로 판정한다.\n\n"
        "[표 4]\n절차서 3 | 검사번호 | KR-I-NSAM-03.01 | 형태 검사 일반구조 외함\n\n"
        "[그림 5]\n절차서 4 | 검사번호 | KR-I-NSAM-04.01 | 형태 검사 전환부\n"
    )
    pages = [
        "절차서 2 검사번호 KR-I-NSAM-02.01 공급확인서 및 성적서로 판정한다.",
        "절차서 3 검사번호 KR-I-NSAM-03.01 형태 검사 일반구조 외함",
        "절차서 4 검사번호 KR-I-NSAM-04.01 형태 검사 전환부",
    ]

    pieces = split_text_by_pages(body, pages)

    assert pieces is not None
    assert "[표 4]" not in pieces[0] and pieces[1].startswith("[표 4]")
    assert pieces[2].startswith("[그림 5]")
    assert "".join(pieces) == body
