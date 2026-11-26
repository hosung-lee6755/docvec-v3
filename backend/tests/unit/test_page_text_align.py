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


# ------------------------------------------------- 저장된 쪽 정보(page_map)와 고르기

def test_prefers_the_stored_page_map_when_page_starts_cannot_be_found():
    # 미리보기 쪽이 본문에 없는 머리말과 목차 칸으로 시작하면 첫머리 찾기는 쪽을 비우고 내용을 앞 쪽에 몰았다
    # (항만수요예측 결과보고서 5쪽에 2~3쪽 목차가 나왔다, 2026-11-25). 처리 때 맞춘 page_map 이 더 맞으면 그것을 쓴다
    from app.services.page_text_align import split_text_for_preview

    body = "표지 제목\n목차 과업 개요 1\n과업 개요 본문은 항만 수요 예측을 다룬다\n과업 범위 본문은 품목별 모형을 다룬다\n"
    first = body.index("과업 개요 본문")
    second = body.index("과업 범위 본문")
    page_map = [[first, 1], [second, 2], [len(body), 3]]
    pages = [
        "머리말 표지 제목 목차 과업 개요 ---- 1",
        "머리말 과업 개요 본문은 항만 수요 예측을 다룬다",
        "머리말 과업 범위 본문은 품목별 모형을 다룬다",
    ]

    pieces = split_text_for_preview(body, page_map, pages)

    assert pieces is not None
    assert "과업 개요 본문" in pieces[1] and "과업 범위 본문" in pieces[2]


def test_falls_back_to_page_starts_when_the_page_map_has_one_page():
    from app.services.page_text_align import split_text_for_preview

    pages = [
        "제1장 총칙 이 지침은 조사료 생산기반 확충 사업의",
        "제2장 사업 대상 사업 대상은 축산 농가와 생산자 단체로 한다.",
        "제3장 지원 기준 지원 기준은 사업량과 단가에 따른다.",
    ]

    pieces = split_text_for_preview(BODY, [[len(BODY), 1]], pages)

    assert pieces is not None and pieces[1].startswith("제2장") and pieces[2].startswith("제3장")


def test_page_map_pages_beyond_the_preview_go_to_its_last_page():
    from app.services.page_text_align import pages_from_page_map

    assert pages_from_page_map("가나다라", [[1, 1], [2, 2], [4, 5]], 2) == ["가", "나다라"]
    assert pages_from_page_map("가나", [[2, 1]], 2) is None


def test_running_headers_on_every_preview_page_do_not_pull_page_starts_forward():
    # AIDE 검수기준서 DOCX(2026-11-25): 미리보기 쪽마다 "AIDE | Driver DNA™ Prototype / 검수기준서 / Page N" 머리말이
    # 있고 본문에는 없다. 머리말로 첫머리를 찾다가 2~7쪽이 비고 8쪽에 모든 글이 몰렸다
    bodies = [
        "성과물 검수기준서 표지와 문서 개요를 담은 첫 쪽이다.",
        "제외 영역과 검수 범위를 정의하는 둘째 쪽의 본문 내용이다.",
        "검수 항목별 판정 기준을 설명하는 셋째 쪽의 본문 내용이다.",
        "검수 데이터셋 구성 방식을 적은 넷째 쪽의 본문 내용이다.",
    ]
    header = "AIDE | Driver DNA™ Prototype\n검수기준서\nPage {n}\n"
    pages = [bodies[0]] + [header.format(n=n) + body for n, body in enumerate(bodies[1:], start=2)]
    text = "AIDE Driver DNA Prototype 개요\n" + "\n".join(bodies)

    pieces = split_text_by_pages(text, pages)

    assert [piece.strip().splitlines()[-1] for piece in pieces] == bodies


def test_a_page_start_that_also_appears_earlier_as_a_phrase_is_matched_where_the_page_really_begins():
    # AIDE 구축제안서 DOCX(2026-11-25): 3쪽 첫머리 "Risk Scoring Engine"이 2쪽 본문 문장에도 나와서 3쪽이 2쪽 본문
    # 가운데서 시작했다. 첫머리 뒤의 글까지 이어서 맞는 자리를 쓴다
    pages = [
        "제안서 표지",
        "배경 및 목적. 데이터 파이프라인, Risk Scoring Engine, Driver DNA 를 단계적으로 개발한다.",
        "Risk Scoring Engine Rule Engine 위험징후 여덟 단계와 ADAS 이벤트를 복합해 점수를 낸다.",
    ]
    text = "\n".join(pages)

    pieces = split_text_by_pages(text, pages)

    assert pieces[1].strip() == pages[1]
    assert pieces[2].strip() == pages[2]


REPEATED = "번호 변수명 BDI_Open 환율 생산지수 소비자심리지수 평균 가중치 비교 표"
REPEATED_PAGES = [
    "표지 물동량 영향요인 분석 보고서 제1권",
    f"철광석 요인 분석 결과를 정리한다 {REPEATED} 철광석 결론 문장은 여기서 끝난다",
    f"{REPEATED} 석탄 결론 문장은 별도로 쓴다 그리고 끝맺음",
]


def test_alignment_picks_the_occurrence_whose_following_text_matches_the_page():
    # 물동량 영향요인 분석 HWP(2026-11-25): 같은 변수 표가 품목마다 되풀이돼, 쪽 첫머리가 앞 쪽 표에 먼저 맞고
    # 32자를 이어 봐도 같았다. 92쪽부터 77쪽이 비었다. 뒤 글이 그 쪽 글과 가장 잘 맞는 자리를 고른다
    from app.services.page_text_align import split_text_by_alignment

    text = "\n".join(REPEATED_PAGES)

    greedy = split_text_by_pages(text, REPEATED_PAGES)
    pieces = split_text_by_alignment(text, REPEATED_PAGES)

    assert "철광석 결론" not in greedy[1]  # 예전 방식은 2쪽을 표 앞에서 끊었다
    assert "철광석 결론" in pieces[1]
    assert pieces[2].startswith(REPEATED) and "석탄 결론" in pieces[2]


def test_preview_split_uses_the_alignment_when_it_fits_best():
    from app.services.page_text_align import split_text_for_preview

    text = "\n".join(REPEATED_PAGES)

    pieces = split_text_for_preview(text, None, REPEATED_PAGES)

    assert "철광석 결론" in pieces[1] and "석탄 결론" in pieces[2]


def test_alignment_leaves_a_page_empty_when_its_text_is_not_in_the_body():
    from app.services.page_text_align import split_text_by_alignment

    pages = [*REPEATED_PAGES[:2], "본문에 없는 그림 쪽 설명 글자들만 있다 아무 데도 없다", REPEATED_PAGES[2]]
    text = "\n".join(REPEATED_PAGES)

    pieces = split_text_by_alignment(text, pages)

    assert pieces[2] == "" and "석탄 결론" in pieces[3]
