from app.pipeline.blocks.chunk_strategies import _estimate_token_count


def test_empty_text_is_zero_tokens():
    assert _estimate_token_count("") == 0


def test_pure_hangul_text_counts_roughly_one_token_per_syllable():
    text = "가나다라마바사"  # 7 syllables

    assert _estimate_token_count(text) == 7


def test_pure_latin_text_counts_roughly_one_token_per_four_chars():
    text = "a" * 40  # 40 latin chars

    assert _estimate_token_count(text) == 10


def test_mixed_hangul_and_latin_combines_both_heuristics():
    text = "안녕" + ("a" * 8)  # 2 hangul + 8 latin

    assert _estimate_token_count(text) == 2 + 8 // 4


def test_short_non_empty_text_is_at_least_one_token():
    assert _estimate_token_count("a") == 1
