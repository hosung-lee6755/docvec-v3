from app.services.page_boundaries import _choose, refine_boundaries

A = "가. 항만 물동량 예측 모델은 과거 실적을 바탕으로 품목별 변화 요인을 선정하고 검증한다.\n\n"
B = "나. 학계의 연구에서는 품목에 따른 물동량 변화 요인을 도출하고 예측 모델의 정확성을 검증하였다.\n\n"
C = "다. 환적 컨테이너는 국내 컨테이너 물동량에서 큰 비중을 차지하며 최근 증가세가 높아지고 있다.\n\n"
D = "라. 국내 환적 물동량의 대부분이 부산항에서 처리되고 있어 항만별 특성을 고려해야 한다.\n\n"
TEXT = A + B + C + D
PAGES = [A + B, C + D]


def test_each_page_turn_takes_the_cut_that_fits_both_neighbouring_pages():
    # 2026-11-27: 문서 전체 평균으로 고른 한 방식을 모든 쪽 경계에 써, 그 방식이 틀린 경계에서는 다음 쪽 첫 문단이
    # 앞 쪽 끝에 붙었다(컨설팅 HWP 30쪽). 경계마다 후보 위치 가운데 앞뒤 두 쪽 원본 글과 가장 많이 맞는 곳을 고른다
    too_late = [A + B + C, D]
    too_early = [A, B + C + D]

    for chosen in (too_late, too_early):
        pieces = refine_boundaries(chosen, [too_late, too_early], PAGES)

        assert pieces == [A + B, C + D]


def test_a_paragraph_border_near_the_candidates_is_also_tried():
    # 모든 후보가 같은 곳에서 틀려도, 그 둘레의 문단 경계 가운데 더 맞는 곳으로 옮긴다
    wrong = [A + B + C, D]

    assert refine_boundaries(wrong, [wrong], PAGES) == [A + B, C + D]


def test_a_paragraph_crossing_the_page_turn_is_cut_at_the_word_where_the_page_turns():
    # 문단 하나가 쪽을 넘어가면 원본은 문장 가운데에서 쪽이 바뀐다. 문단 경계에서만 자르면 문단 전체가 한 쪽에 들어가
    # 뒤 쪽 글이 앞 쪽에 보였다(과업지시서 4쪽, 제안요청서 75쪽, 2026-11-27)
    head = "제12조 중도탈퇴에 대한 조치 공동수급체의 구성원은 다음 각호의 어느 하나에 "
    tail = "해당하는 경우 외에는 입찰 및 해당계약의 이행을 완료하는 날까지 탈퇴할 수 없다."
    text = A + head + tail + "\n\n" + D
    pages = [A + head, tail + D]

    pieces = refine_boundaries([A + head + tail + "\n\n", D], [], pages)

    assert pieces == [A + head, tail + "\n\n" + D]


def test_a_table_crossing_the_page_turn_is_cut_between_the_rows_on_each_page():
    rows = [f"| 바다모래 허가공급량 | 바다모래_허가공급_{name} | 2005~2023 |\n" for name in ("인천", "경기", "강원", "충북", "세종", "전북")]
    table = "| 구분 | 변수 | 기간 |\n|---|---|---|\n" + "".join(rows) + "\n"
    pages = [A + "구분 변수 기간 " + "".join(rows[:3]), "".join(rows[3:]) + D]

    pieces = refine_boundaries([A + table, D], [], pages)

    assert pieces[0].endswith(rows[2]) and pieces[1].startswith(rows[3])


def test_a_flat_score_lets_the_recall_pick_the_cut_and_a_recall_drop_blocks_a_score_gain():
    # 지역 이름만 다른 행이 이어지는 표는 덧셈 점수가 거의 평평해 재현율로 고른다(물동량 영향요인 126쪽). 덧셈 점수가
    # 올라도 재현율이 떨어지는 곳(한 쪽이 비는 곳)으로는 옮기지 않는다(같은 문서 129쪽, 2026-11-27)
    text = "x" * 40
    options = [0, 10, 20, 30]

    flat = _choose(text, options, 30, {0: 92, 10: 94, 20: 92, 30: 92}, {0: 1.5, 10: 1.93, 20: 1.80, 30: 1.78})
    emptying = _choose(text, options, 10, {0: 99, 10: 90, 20: 91, 30: 92}, {0: 1.0, 10: 1.9, 20: 1.9, 30: 1.9})

    assert flat == 10
    assert emptying == 10


def test_text_found_on_no_page_does_not_move_the_cut():
    # 미리보기에 없는 글(그림 안 글 등)은 어느 쪽에 두어도 맞음이 같으므로 처음 경계를 지킨다
    extra = "그림 안에서 읽은 글자 묶음 축 눈금 라벨 범례 값 모음 자료 출처 표기\n\n"
    text_pieces = [A + B + extra, C + D]

    assert refine_boundaries(text_pieces, [text_pieces], PAGES) == text_pieces


def test_pieces_that_do_not_rebuild_the_text_are_left_alone():
    pieces = [A + B, C + D]

    assert refine_boundaries(pieces, [[A, C]], PAGES) == pieces
    assert "".join(refine_boundaries(pieces, [pieces], PAGES)) == TEXT
