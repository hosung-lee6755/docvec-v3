from app.pipeline.blocks.chunk_strategies import group_children_into_parents


def _span(text, start, end, section_path=None):
    return (text, text, start, end, section_path or [], [])


def test_consecutive_spans_sharing_section_path_group_together():
    spans = [
        _span("a", 0, 10, ["1장"]),
        _span("b", 10, 20, ["1장"]),
        _span("c", 20, 30, ["1장"]),
    ]

    groups = group_children_into_parents(spans, max_chars=1000)

    assert groups == [[0, 1, 2]]


def test_section_path_change_starts_a_new_group():
    spans = [
        _span("a", 0, 10, ["1장"]),
        _span("b", 10, 20, ["1장"]),
        _span("c", 20, 30, ["2장"]),
    ]

    groups = group_children_into_parents(spans, max_chars=1000)

    assert groups == [[0, 1], [2]]


def test_flat_spans_with_no_section_path_fall_back_to_fixed_group_size():
    spans = [_span(str(i), i * 10, i * 10 + 10) for i in range(12)]

    groups = group_children_into_parents(spans, max_chars=1000)

    assert groups == [[0, 1, 2, 3, 4], [5, 6, 7, 8, 9], [10, 11]]


def test_oversized_group_is_cut_even_within_the_same_section():
    # max_chars=10, multiplier=4 -> parent cap is 40 chars.
    spans = [
        _span("a", 0, 15, ["1장"]),
        _span("b", 15, 30, ["1장"]),
        _span("c", 30, 45, ["1장"]),
    ]

    groups = group_children_into_parents(spans, max_chars=10)

    assert groups == [[0, 1], [2]]


def test_single_span_forms_its_own_group():
    spans = [_span("only", 0, 5, ["1장"])]

    groups = group_children_into_parents(spans, max_chars=1000)

    assert groups == [[0]]


def test_sibling_subsections_share_their_upper_section_parent():
    # 세부 절이 많은 문서에서 parent가 child와 1:1이 되던 문제(2026-11-13)
    spans = [
        _span("a", 0, 10, ["2장", "2.1", "2.1.1"]),
        _span("b", 10, 20, ["2장", "2.1", "2.1.2"]),
        _span("c", 20, 30, ["2장", "2.1", "2.1.3"]),
        _span("d", 30, 40, ["2장", "2.2", "2.2.1"]),
    ]

    groups = group_children_into_parents(spans, max_chars=1000)

    assert groups == [[0, 1, 2], [3]]


def test_section_intro_and_its_subsections_group_together():
    spans = [
        _span("a", 0, 10, ["2장", "2.1"]),
        _span("b", 10, 20, ["2장", "2.1", "2.1.1"]),
        _span("c", 20, 30, ["2장", "2.2"]),
        _span("d", 30, 40, ["3장"]),
    ]

    groups = group_children_into_parents(spans, max_chars=1000)

    assert groups == [[0, 1, 2], [3]]


def test_flat_span_does_not_join_a_sectioned_group():
    spans = [_span("a", 0, 10, ["1장"]), _span("b", 10, 20), _span("c", 20, 30)]

    groups = group_children_into_parents(spans, max_chars=1000)

    assert groups == [[0], [1, 2]]


def test_pieces_of_one_large_table_share_a_single_parent():
    # 고도화보고서 [표 74]: 큰 표를 나눈 조각은 모두 표 전체 범위(0~6097)를 공유한다. 예전에는 둘째 조각부터
    # "묶음이 너무 크다"에 걸려 조각마다 표 전체를 담은 parent 가 새로 생겨 같은 글이 4번 저장됐다(2026-11-20 감사)
    table = [(f"[표 74] (부분 {i}/4)", "raw", 0, 6097, ["부록 E"], ["t"]) for i in range(1, 5)]
    after = [("다음 문단", "raw", 6100, 6200, ["부록 E"], ["p"])]

    groups = group_children_into_parents(table + after, 500)

    assert groups[0] == [0, 1, 2, 3]
    assert sum(len(g) for g in groups) == 5
