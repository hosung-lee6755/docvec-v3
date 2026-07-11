"""Coverage for app.services.dictionary_service — the kiwipiepy-backed Korean
tokenizer that replaced BM25's naive `.split()`, plus the admin-managed
stopword/synonym/custom-word ("user dictionary") layered on top of it, per
문서_처리_사전_스키마.md."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import dictionary_service


def _variant(term: str):
    return MagicMock(variant_term=term)


def _entry(
    entry_type: str,
    term: str,
    variants: list[str] | None = None,
    match_type: str | None = None,
    direction: str | None = None,
    processing_mode: str | None = None,
    processing_rule: str | None = None,
    case_sensitive: bool = False,
):
    return MagicMock(
        entry_type=entry_type,
        term=term,
        variants=[_variant(v) for v in (variants or [])],
        match_type=match_type,
        direction=direction,
        processing_mode=processing_mode,
        processing_rule=processing_rule,
        case_sensitive=case_sensitive,
    )


@pytest.fixture(autouse=True)
def _restore_cache():
    original = (
        dictionary_service._kiwi,
        dictionary_service._stopwords,
        dictionary_service._stopword_rules,
        dictionary_service._expand_map,
        dictionary_service._bidirectional_map,
        dictionary_service._search_expand_variant_to_canonical,
        dictionary_service._search_expand_canonical_to_variants,
    )
    yield
    (
        dictionary_service._kiwi,
        dictionary_service._stopwords,
        dictionary_service._stopword_rules,
        dictionary_service._expand_map,
        dictionary_service._bidirectional_map,
        dictionary_service._search_expand_variant_to_canonical,
        dictionary_service._search_expand_canonical_to_variants,
    ) = original


async def _refresh(entries):
    db = AsyncMock()
    db.scalars.return_value = MagicMock(all=MagicMock(return_value=entries))
    await dictionary_service.refresh_dictionary_cache(db)


def test_tokenize_strips_particles_and_endings():
    tokens = dictionary_service.tokenize("전세계약서를 검토하고 계약금을 입금했다")

    assert "를" not in tokens
    assert "다" not in tokens
    assert "계약서" in tokens
    assert "계약금" in tokens


def test_tokenize_batch_matches_tokenize_for_single_text():
    text = "전세계약서를 검토했다"
    assert dictionary_service.tokenize_batch([text])[0] == dictionary_service.tokenize(text)


def test_tokenize_batch_returns_empty_list_for_no_texts():
    assert dictionary_service.tokenize_batch([]) == []


@pytest.mark.asyncio
async def test_stopword_exact_match_filters_only_exact_token():
    await _refresh([_entry("stopword", "검토", match_type="EXACT")])
    tokens = dictionary_service.tokenize("전세계약서를 검토하고 계약금을 입금했다")

    assert "검토" not in tokens
    assert "계약금" in tokens


@pytest.mark.asyncio
async def test_stopword_contains_match_filters_substring():
    await _refresh([_entry("stopword", "약", match_type="CONTAINS")])
    tokens = dictionary_service.tokenize("전세계약서를 검토했다")

    assert "계약서" not in tokens  # contains "약"
    assert "전세" in tokens


@pytest.mark.asyncio
async def test_stopword_prefix_and_suffix_match():
    await _refresh([
        _entry("stopword", "계약", match_type="PREFIX"),
        _entry("stopword", "금", match_type="SUFFIX"),
    ])
    tokens = dictionary_service.tokenize("전세계약서를 검토했다 계약금을 입금했다")

    assert "계약서" not in tokens  # starts with "계약"
    assert "계약금" not in tokens  # ends with "금"
    assert "전세" in tokens


@pytest.mark.asyncio
async def test_disabled_entries_are_excluded_from_cache():
    db = AsyncMock()
    db.scalars.return_value = MagicMock(all=MagicMock(return_value=[]))
    await dictionary_service.refresh_dictionary_cache(db)
    # enabled.is_(True) filter is applied at the query level — verify the
    # query was actually filtered rather than trusting an empty result.
    call_args = db.scalars.call_args[0][0]
    assert "enabled" in str(call_args).lower()


@pytest.mark.asyncio
async def test_synonym_one_way_expands_variant_to_canonical_only():
    await _refresh([
        _entry("synonym", "임대", variants=["전세"], direction="ONE_WAY"),
    ])
    variant_tokens = dictionary_service.tokenize("전세 계약")
    canonical_tokens = dictionary_service.tokenize("임대 계약")

    assert "임대" in variant_tokens
    assert "전세" not in canonical_tokens  # ONE_WAY: canonical does not expand back


@pytest.mark.asyncio
async def test_synonym_bidirectional_expands_both_ways():
    await _refresh([
        _entry("synonym", "임대", variants=["전세"], direction="BIDIRECTIONAL"),
    ])
    canonical_tokens = dictionary_service.tokenize("임대 계약")

    assert "전세" in canonical_tokens


@pytest.mark.asyncio
async def test_custom_word_keep_registers_as_single_token_without_expansion():
    await _refresh([
        _entry(
            "custom_word", "불용어테스트", variants=["불용어테"],
            processing_rule="KEEP",
        ),
    ])
    tokens = dictionary_service.tokenize("불용어테스트를 확인했다")

    assert "불용어테스트" in tokens
    assert "불용어" not in tokens


@pytest.mark.asyncio
async def test_custom_word_normalize_expands_variant_to_standard_term():
    await _refresh([
        _entry(
            "custom_word", "랭그래프", variants=["랭 그래프"],
            processing_rule="NORMALIZE",
        ),
    ])
    tokens = dictionary_service.tokenize("랭 그래프 사용법")

    assert "랭그래프" in tokens


@pytest.mark.asyncio
async def test_custom_word_ignore_is_not_registered_with_kiwi():
    await _refresh([
        _entry("custom_word", "불용어테스트", processing_rule="IGNORE"),
    ])
    tokens = dictionary_service.tokenize("불용어테스트를 확인했다")

    # Not registered as a user word, so kiwi falls back to its default split.
    assert "불용어테스트" not in tokens


def test_expand_query_returns_unchanged_when_no_dictionary_entries():
    query, added = dictionary_service.expand_query("인공지능 활용 사례")

    assert query == "인공지능 활용 사례"
    assert added == []


@pytest.mark.asyncio
async def test_expand_query_one_way_expands_variant_to_canonical_only():
    await _refresh([
        _entry(
            "synonym", "인공지능", variants=["AI"],
            direction="ONE_WAY", processing_mode="SEARCH_EXPAND",
        ),
    ])

    variant_query, variant_added = dictionary_service.expand_query("AI 도입 전략")
    canonical_query, canonical_added = dictionary_service.expand_query("인공지능 도입 전략")

    assert variant_added == ["인공지능"]
    assert variant_query == "AI 도입 전략 인공지능"
    # ONE_WAY: canonical term present does not pull the variant back in
    assert canonical_added == []
    assert canonical_query == "인공지능 도입 전략"


@pytest.mark.asyncio
async def test_expand_query_bidirectional_expands_both_directions():
    await _refresh([
        _entry(
            "synonym", "인공지능", variants=["AI"],
            direction="BIDIRECTIONAL", processing_mode="SEARCH_EXPAND",
        ),
    ])

    canonical_query, canonical_added = dictionary_service.expand_query("인공지능 도입 전략")

    assert canonical_added == ["AI"]
    assert canonical_query == "인공지능 도입 전략 AI"


@pytest.mark.asyncio
async def test_expand_query_ignores_entries_without_search_expand_mode():
    await _refresh([
        _entry(
            "synonym", "인공지능", variants=["AI"],
            direction="BIDIRECTIONAL", processing_mode="NORMALIZE",
        ),
    ])

    query, added = dictionary_service.expand_query("AI 도입 전략")

    assert added == []
    assert query == "AI 도입 전략"


@pytest.mark.asyncio
async def test_expand_query_does_not_duplicate_term_already_in_query():
    await _refresh([
        _entry(
            "synonym", "인공지능", variants=["AI"],
            direction="BIDIRECTIONAL", processing_mode="SEARCH_EXPAND",
        ),
    ])

    query, added = dictionary_service.expand_query("AI 는 인공지능의 줄임말")

    assert added == []
    assert query == "AI 는 인공지능의 줄임말"
