from app.pipeline.blocks.normalization_blocks import _diff_sample


def test_change_near_start_is_captured():
    before = "abc def"
    after = "abcXdef"

    before_sample, after_sample = _diff_sample(before, after)

    assert before_sample == before
    assert after_sample == after


def test_change_after_200_chars_is_not_hidden_by_head_slice():
    # 정제 비교 탭 버그(9항목 펀치리스트 #8) 회귀 테스트 — 앞 200자만 자르면
    # 뒤쪽에서만 발생한 변경은 before_sample == after_sample이 되어 "변경
    # 없음"처럼 보인다.
    before = ("가" * 250) + "-\n" + ("나" * 10)
    after = ("가" * 250) + ("나" * 10)

    before_sample, after_sample = _diff_sample(before, after)

    assert before_sample != after_sample
    assert "-\n" in before_sample
    assert "-\n" not in after_sample


def test_window_is_centered_on_diff_position_not_document_start():
    before = ("x" * 500) + "A" + ("x" * 500)
    after = ("x" * 500) + "B" + ("x" * 500)

    before_sample, after_sample = _diff_sample(before, after, window=20)

    assert "A" in before_sample
    assert "B" in after_sample
    assert len(before_sample) <= 40
    assert len(after_sample) <= 40


def test_trailing_only_difference_at_string_end():
    before = "same text here"
    after = "same text here EXTRA"

    before_sample, after_sample = _diff_sample(before, after, window=10)

    assert before_sample != after_sample
    assert "EXTRA" in after_sample
