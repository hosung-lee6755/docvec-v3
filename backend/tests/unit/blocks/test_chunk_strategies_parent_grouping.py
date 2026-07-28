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
