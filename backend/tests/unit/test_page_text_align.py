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


def test_number_rows_of_a_table_spanning_pages_are_not_taken_for_running_lines():
    # 예측분석 설계보고서 HWP(2026-11-26): 여러 쪽에 걸친 숫자 표에서 "13,229", "360,196" 같은 줄이 숫자를 "#" 로
    # 바꾸면 모두 "#,#" 로 같아져 쪽마다 되풀이되는 머리말로 지워졌다. 쪽 첫머리를 못 찾아 12·13쪽이 비고 표가 11쪽에 몰렸다
    models = ["Prophet", "ARIMA", "LightGBM", "XGBoost", "RandomForest", "Regression", "CatBoost", "ElasticNet"]
    rows = [f"| {m} | {i}0,{i}11 | {i}1,{i}22 | {i}2,{i}33 |" for i, m in enumerate(models, start=1)]
    body = "[표 4] 항만별 예측 결과\n" + "\n".join(rows) + "\n"

    def page(numbered: list[tuple[int, str]]) -> str:
        return "\n".join(f"{m}\n{i}0,{i}11\n{i}1,{i}22\n{i}2,{i}33" for i, m in numbered)

    numbered = list(enumerate(models, start=1))
    pages = ["[표 4] 항만별 예측 결과\n평택\n" + page(numbered[:2]), page(numbered[2:5]), page(numbered[5:])]

    pieces = split_text_by_pages(body, pages)

    assert pieces is not None and all(piece.strip() for piece in pieces)
    assert pieces[1].startswith("| LightGBM |") and pieces[2].startswith("| Regression |")
    assert "".join(pieces) == body


def test_page_numbers_are_still_running_lines():
    # 쪽 번호("- 3 -")는 숫자 줄이어도 여전히 되풀이 줄로 빼고 찾는다
    topics = ["총칙과 목적", "사업 대상 선정", "지원 기준 산정", "사후 관리 절차"]
    pages = [f"- {n} -\n제{n}장 {topic}을 적은 쪽입니다" for n, topic in enumerate(topics, start=1)]
    body = "".join(f"제{n}장 {topic}을 적은 쪽입니다\n" for n, topic in enumerate(topics, start=1))

    pieces = split_text_by_pages(body, pages)

    assert pieces is not None and [p.split()[0] for p in pieces] == ["제1장", "제2장", "제3장", "제4장"]


def test_global_alignment_places_page_starts_inside_paragraphs_that_cross_pages():
    # 예측분석 설계보고서 HWP(2026-11-26): 미리보기가 줄을 다시 배치해 문단이 쪽 경계에 걸치면, 쪽 첫머리 16자 찾기가
    # 앞 쪽 끝 문단부터 쪽을 시작하거나 다음 쪽 첫 문단까지 끌어왔다. 전체 글을 맞춰 쪽 경계를 옮긴다
    from app.services.page_text_align import split_text_by_global_alignment

    paragraphs = [
        "통계 기반 요인 분석은 두 변수의 선형 관계를 상관계수로 측정하는 방법이며 그랜저 인과관계 검정을 함께 쓴다.",
        "머신러닝 기반 요인 분석은 랜덤 포레스트로 변수 중요도를 구하는 보루타 알고리즘을 쓴다.",
        "시계열성 탐색은 평균 회귀와 변동 폭을 그래프로 보고 정상성 검정을 진행한다.",
        "데이터 보간법은 결측치를 이동평균이나 선형 보간으로 채운다.",
        "ARIMA 모형은 자기회귀와 이동평균을 결합한 시계열 예측 모형이다.",
    ]
    body = "\n\n".join(paragraphs) + "\n"
    pages = [
        "보고서 머리말\n" + paragraphs[0] + "\n" + paragraphs[1][:20],
        "보고서 머리말\n" + paragraphs[1][20:] + "\n" + paragraphs[2] + "\n" + paragraphs[3],
        "보고서 머리말\n" + paragraphs[4],
    ]

    pieces = split_text_by_global_alignment(body, pages)

    assert pieces is not None and "".join(pieces) == body
    assert "통계 기반" in pieces[0] and "통계 기반" not in pieces[1]
    assert "데이터 보간법" in pieces[1] and "ARIMA" not in pieces[1] and pieces[2].startswith("ARIMA")


def test_a_long_paragraph_crossing_pages_is_split_where_the_page_turns():
    # 분석결과보고서 HWP(2026-11-26): HWP 문단은 본문에서 한 줄이라, 쪽 경계가 문단 가운데에 걸리면 줄 처음으로 당겨
    # 여러 줄짜리 문단이 통째로 앞 쪽에 붙었다. 원본은 문단 중간에서 쪽이 넘어간다. 멀리 당겨야 하면 그 자리 앞 띄어쓰기에서 자른다
    first = "가. 수용가 보유 기간 분석 결과 천안은 3개월 이하 수용가가 21개, 6개월 이하 수용가가 34개로 단기 비중이 크다"
    second = "청주는 3개월 이하 수용가가 1개, 6개월 이하 수용가가 13개로 크게 증가하며 설비는 상대적으로 적다"
    body = f"1) 데이터 기간 분포\n{first} {second}\n나. 대불은 평균 보유 기간이 4개월에 불과하다\n"
    pages = [f"1) 데이터 기간 분포 {first}", f"{second}\n나. 대불은 평균 보유 기간이 4개월에 불과하다"]

    pieces = split_text_by_pages(body, pages)

    assert pieces is not None and "".join(pieces) == body
    assert pieces[0].rstrip().endswith("단기 비중이 크다") and pieces[1].startswith("청주는")


def test_a_short_pull_to_the_line_start_is_kept():
    body = "제1장 총칙\n가나다라마바사 아자차카타파하\n제2장 대상\n"
    pages = ["제1장 총칙 가나다라마바사", "아자차카타파하 제2장 대상"]

    pieces = split_text_by_pages(body, pages)

    assert pieces is not None and pieces[1].startswith("가나다라마바사")


def test_a_long_table_row_is_not_split_across_pages():
    row = "| 천안 | 3개월 이하 수용가 21개, 6개월 이하 수용가 34개 | 단기 비중이 크고 설비 보유 기간은 짧다 | 비고 없음 |"
    body = f"[표 2] 보유 기간\n| 구분 | 내용 | 해석 | 비고 |\n{row}\n"
    pages = ["[표 2] 보유 기간 구분 내용 해석 비고 천안 3개월 이하 수용가 21개, 6개월 이하 수용가 34개",
             "단기 비중이 크고 설비 보유 기간은 짧다 비고 없음"]

    pieces = split_text_by_pages(body, pages)

    assert pieces is not None and all(not piece or piece.startswith(("[표", "|")) for piece in pieces)


def test_a_one_page_preview_gets_the_whole_parsed_text():
    # 미리보기가 한 쪽뿐인 문서(시트 하나인 엑셀)는 파싱 본문 전체가 그 쪽이다. 예전에는 None 이 나와 원문 대조의
    # 파싱 쪽에 미리보기에서 뽑은 원본 글이 대신 나왔다(2026-11-26)
    from app.services.page_text_align import split_text_for_preview

    body = "| 항목 | 설명 |\n| --- | --- |\n| 카드번호 | 결제 카드 |\n"

    assert split_text_for_preview(body, [[len(body), 1]], ["항목 설명 카드번호 결제 카드"]) == [body]
    assert split_text_for_preview(body, None, ["anything"]) == [body]
    assert split_text_for_preview("", None, ["anything"]) is None


def test_a_boxed_paragraph_crossing_pages_is_split_where_the_page_turns():
    # 한 칸짜리 표(글상자)가 두 쪽에 걸치면 표 한 줄이 쪽 하나보다 길다. 줄 처음으로 당기면 앞 쪽이 통째로 비었다
    # (조사료 사업시행지침 HWPX 26쪽, 2026-11-26). 이런 줄은 칸 안 줄바꿈(" / ")에서 자른다
    first = [f"◦ 첫 쪽 항목 {i}번은 조사료 생산 기반을 넓히는 사업 대상자 선정 기준이다" for i in range(12)]
    second = [f"· 둘째 쪽 항목 {i}번은 축산법 위반 농가 지원 제한 기준을 설명한다" for i in range(12)]
    body = "앞 문단입니다.\n\n[표 37]\n| " + " / ".join(first + second) + " |\n|---|\n\n○ 구비서류\n"
    pages = ["앞 문단입니다.\n" + "\n".join(first), "\n".join(second) + "\n○ 구비서류"]

    pieces = split_text_by_pages(body, pages)

    assert pieces is not None and "".join(pieces) == body
    assert "첫 쪽 항목 11번" in pieces[0] and "둘째 쪽 항목 0번" not in pieces[0]
    assert pieces[1].startswith("· 둘째 쪽 항목 0번")


def test_a_page_without_unique_text_still_gets_its_share_by_global_alignment():
    # 나라 이름만 다른 표가 되풀이되면 쪽 안의 글 조각이 모두 다른 쪽에도 있어 기준점이 없다. 예전에는 그 쪽이
    # 통째로 비고 내용이 앞 쪽에 붙었다(물동량 영향요인 분석 HWP 20쪽 등 12쪽, 2026-11-26)
    from app.services.page_text_align import split_text_by_global_alignment

    table = "\n".join(f"| Exchange rate series {i} | 1990.01~2026.11 | monthly |" for i in range(6))
    intro = "첫 쪽은 러시아 지표 설명으로 시작하며 환율과 물가를 함께 본다."
    outro = "셋째 쪽 끝에는 중국 지표 정리와 다음 장 안내가 따로 나온다."
    body = f"{intro}\n{table}\n{table}\n{outro}\n"
    pages = [intro, table, f"{table}\n{outro}"]

    pieces = split_text_by_global_alignment(body, pages)

    assert pieces is not None and "".join(pieces) == body
    assert all(piece.strip() for piece in pieces)
    assert pieces[1].startswith("| Exchange rate series 0")


def test_a_long_cell_crossing_pages_is_cut_near_the_page_turn_not_at_a_far_cell_border():
    # 긴 표 칸이 쪽을 넘으면 쪽이 넘어간 자리 가까이에서 잘라야 한다. 멀리 있는 칸 경계까지 당기면 앞 쪽 칸 글
    # 수백 자가 다음 쪽으로 넘어갔다(고도화보고서 HTML 97쪽, 2026-11-26)
    first = " ".join(f"앞쪽 문장 {i}번은 매일 배치 시간을 측정한 결과를 적는다." for i in range(12))
    second = " ".join(f"뒤쪽 문장 {i}번은 리포트 생성 시간이 회사 수를 따른다고 적는다." for i in range(12))
    body = f"[표 9]\n| 항목 | 내용 | 관련 |\n|---|---|---|\n| 처리 시간 | {first} {second} | 7.1 |\n\n다음 문단\n"
    pages = [f"항목 내용 관련 처리 시간 {first}", f"항목 내용 관련 {second} 7.1 다음 문단"]

    pieces = split_text_by_pages(body, pages)

    assert pieces is not None and "".join(pieces) == body
    assert pieces[0].rstrip().endswith("11번은 매일 배치 시간을 측정한 결과를 적는다.")
    assert pieces[1].startswith("뒤쪽 문장 0번")


def test_a_floating_table_printed_at_the_end_of_the_next_page_text_moves_to_that_page():
    # 컨설팅 HWP: 14쪽 위의 [표 4] 는 미리보기 글자 층에서 14쪽 글 끝에 나와 쪽 첫머리 맞춤이 13쪽 끝에 붙였다(2026-11-26)
    from app.services.page_text_align import move_edge_tables

    table = "| 연구자 | 내용 | 변수 |\n|---|---|---|\n| 장원익(2010) | 2010년 철광석 물동량 전망 | 조강생산량과 세계 경제 |\n\n"
    body13 = "철광석은 철강산업의 주원료이다. 철강산업은 자동차와 조선과 기계와 건설에 기초소재를 공급한다.\n\n"
    body14 = "(4) 철재 물동량 예측에 대한 연구 동향\n\n철강산업은 규모의 경제가 실현되는 부문이다.\n\n"
    page13 = "철광석은 철강산업의 주원료이다. 철강산업은 자동차와 조선과 기계와 건설에 기초소재를 공급한다."
    page14 = ("(4) 철재 물동량 예측에 대한 연구 동향 철강산업은 규모의 경제가 실현되는 부문이다. "
              "연구자 내용 변수 장원익(2010) 2010년 철광석 물동량 전망 조강생산량과 세계 경제")

    moved = move_edge_tables([body13 + table, body14], [page13, page14])

    assert moved == [body13, table + body14]
    assert "".join(moved) == body13 + table + body14
    # 표가 원래 쪽 글과 맞으면 그대로 둔다
    assert move_edge_tables([body13 + table, body14], [page13 + " " + page14, page14]) == [body13 + table, body14]
