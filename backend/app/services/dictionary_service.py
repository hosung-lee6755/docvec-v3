import re
import threading

from kiwipiepy import Kiwi
from kiwipiepy.utils import Stopwords
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.dictionary_entry import DictionaryEntry
from app.db.models.dictionary_revision import DictionaryRevision

_lock = threading.Lock()
# Populated eagerly (not lazily) so tokenize() always has a working analyzer,
# even before refresh_dictionary_cache() has run once at startup.
_kiwi = Kiwi()
_stopwords = Stopwords()
_stopword_rules: list[tuple[str, str, bool]] = []  # (match_type, term, case_sensitive)
_expand_map: dict[str, str] = {}  # normalized variant/alias -> canonical/standard term
_bidirectional_map: dict[str, list[str]] = {}  # normalized canonical -> its variants
# Search-time query rewriting (processing_mode == "SEARCH_EXPAND" only — the
# above _expand_map/_bidirectional_map fold every synonym into BM25 tokens
# regardless of processing_mode, which is a separate, coarser mechanism).
# normalized variant -> (canonical term as stored, case_sensitive)
_search_expand_variant_to_canonical: dict[str, tuple[str, bool]] = {}
# normalized canonical (BIDIRECTIONAL only) -> (variant terms as stored, case_sensitive)
_search_expand_canonical_to_variants: dict[str, tuple[list[str], bool]] = {}


def _norm(value: str, case_sensitive: bool) -> str:
    return value if case_sensitive else value.lower()


async def refresh_dictionary_cache(db: AsyncSession) -> None:
    """Rebuild the in-process Kiwi analyzer, stopword rules, and synonym/alias
    expansion maps from the dictionary_entries table (+ their variants).
    Building a Kiwi instance costs several hundred ms, so this runs once at
    API startup and after every dictionary write rather than per search
    request. Disabled entries (enabled=False) are excluded entirely."""
    entries = (await db.scalars(_enabled_entries_stmt())).all()
    _install_entries(entries)


# 채팅 워커는 API 프로세스와 따로 돌아 API 시작 때 채운 캐시를 공유하지 못한다. 워커에서는 사전 개정 번호가
# 바뀌었을 때만 다시 읽는다(v3 마일스톤 6). -1은 아직 한 번도 읽지 않았다는 뜻이다.
_loaded_revision: int | None = -1


def ensure_dictionary_cache_sync(db) -> None:
    """동기 세션(Celery 워커)용. 마지막으로 읽은 뒤 사전이 바뀌었으면 캐시를 다시 만든다."""
    global _loaded_revision
    revision = db.scalar(select(func.max(DictionaryRevision.version)))
    if revision == _loaded_revision:
        return
    entries = db.scalars(_enabled_entries_stmt()).all()
    _install_entries(entries)
    _loaded_revision = revision


def _enabled_entries_stmt():
    return (
        select(DictionaryEntry)
        .where(DictionaryEntry.enabled.is_(True))
        .options(selectinload(DictionaryEntry.variants))
    )


def _install_entries(entries) -> None:
    kiwi = Kiwi()
    stopword_rules: list[tuple[str, str, bool]] = []
    expand_map: dict[str, str] = {}
    bidirectional_map: dict[str, list[str]] = {}
    search_expand_variant_to_canonical: dict[str, tuple[str, bool]] = {}
    search_expand_canonical_to_variants: dict[str, tuple[list[str], bool]] = {}

    for entry in entries:
        variant_terms = [v.variant_term for v in entry.variants]

        if entry.entry_type == "stopword":
            stopword_rules.append((entry.match_type or "EXACT", entry.term, entry.case_sensitive))

        elif entry.entry_type == "synonym":
            for variant in variant_terms:
                expand_map[_norm(variant, entry.case_sensitive)] = entry.term
            if entry.direction == "BIDIRECTIONAL":
                bidirectional_map[_norm(entry.term, entry.case_sensitive)] = variant_terms
            if entry.processing_mode == "SEARCH_EXPAND":
                for variant in variant_terms:
                    search_expand_variant_to_canonical[_norm(variant, entry.case_sensitive)] = (
                        entry.term, entry.case_sensitive,
                    )
                if entry.direction == "BIDIRECTIONAL":
                    search_expand_canonical_to_variants[_norm(entry.term, entry.case_sensitive)] = (
                        variant_terms, entry.case_sensitive,
                    )

        elif entry.entry_type == "custom_word":
            # IGNORE means "known term, but keep out of processing entirely" —
            # matches 문서_처리_사전_스키마.md §3's processingRule semantics.
            if entry.processing_rule == "IGNORE":
                continue
            kiwi.add_user_word(entry.term, "NNP")
            for variant in variant_terms:
                kiwi.add_user_word(variant, "NNP")
            if entry.processing_rule == "NORMALIZE":
                for variant in variant_terms:
                    expand_map[_norm(variant, entry.case_sensitive)] = entry.term

    global _kiwi, _stopwords, _stopword_rules, _expand_map, _bidirectional_map
    global _search_expand_variant_to_canonical, _search_expand_canonical_to_variants
    with _lock:
        _kiwi = kiwi
        _stopwords = Stopwords()
        _stopword_rules = stopword_rules
        _expand_map = expand_map
        _bidirectional_map = bidirectional_map
        _search_expand_variant_to_canonical = search_expand_variant_to_canonical
        _search_expand_canonical_to_variants = search_expand_canonical_to_variants


def _is_stopword(token: str, rules: list[tuple[str, str, bool]]) -> bool:
    for match_type, term, case_sensitive in rules:
        candidate = token if case_sensitive else token.lower()
        needle = term if case_sensitive else term.lower()
        if match_type == "EXACT" and candidate == needle:
            return True
        if match_type == "CONTAINS" and needle in candidate:
            return True
        if match_type == "PREFIX" and candidate.startswith(needle):
            return True
        if match_type == "SUFFIX" and candidate.endswith(needle):
            return True
        if match_type == "REGEX":
            try:
                if re.search(term, token, 0 if case_sensitive else re.IGNORECASE):
                    return True
            except re.error:
                continue
    return False


def tokenize_batch(texts: list[str]) -> list[list[str]]:
    """Korean-morphology-aware tokenizer for BM25 keyword search: strips
    particles/endings via kiwipiepy's default analysis, filters admin-defined
    stopwords (by match_type: EXACT/CONTAINS/PREFIX/SUFFIX/REGEX), and expands
    recognized synonyms/aliases to their canonical/standard term so a query
    using either form matches documents using the other. Batches the
    kiwipiepy call across all texts since per-text calls are ~5x slower."""
    if not texts:
        return []

    with _lock:
        kiwi, stopwords, rules, expand_map, bidirectional_map = (
            _kiwi, _stopwords, _stopword_rules, _expand_map, _bidirectional_map,
        )

    results = []
    for token_list in kiwi.tokenize(texts, stopwords=stopwords):
        tokens = [t.form for t in token_list if not _is_stopword(t.form, rules)]
        expanded = list(tokens)
        for token in tokens:
            lowered = token.lower()
            canonical = expand_map.get(token) or expand_map.get(lowered)
            if canonical:
                expanded.append(canonical)
            extra_variants = bidirectional_map.get(token) or bidirectional_map.get(lowered)
            if extra_variants:
                expanded.extend(extra_variants)
        results.append([t.lower() for t in expanded])
    return results


def tokenize(text: str) -> list[str]:
    return tokenize_batch([text])[0]


def expand_query(query: str) -> tuple[str, list[str]]:
    """Rewrite a search query by appending SEARCH_EXPAND synonym terms whose
    variant or canonical form appears in it, so one search reaches chunks
    phrased with an equivalent term. Matches by substring containment (like
    the stopword CONTAINS rule) rather than kiwi tokenization, since
    dictionary terms are often proper nouns/domain terms that don't
    tokenize cleanly. Returns (query_text_to_embed, added_terms) — added_terms
    is empty when nothing in the dictionary matched, in which case the first
    element is the original query unchanged."""
    with _lock:
        variant_to_canonical = dict(_search_expand_variant_to_canonical)
        canonical_to_variants = dict(_search_expand_canonical_to_variants)

    def _present(term: str, case_sensitive: bool) -> bool:
        haystack = query if case_sensitive else query.lower()
        needle = term if case_sensitive else term.lower()
        return needle in haystack

    added: list[str] = []

    for norm_variant, (canonical, case_sensitive) in variant_to_canonical.items():
        haystack = query if case_sensitive else query.lower()
        if norm_variant in haystack and canonical not in added and not _present(canonical, case_sensitive):
            added.append(canonical)

    for norm_canonical, (variants, case_sensitive) in canonical_to_variants.items():
        haystack = query if case_sensitive else query.lower()
        if norm_canonical in haystack:
            for variant in variants:
                if variant not in added and not _present(variant, case_sensitive):
                    added.append(variant)

    if not added:
        return query, []
    return f"{query} {' '.join(added)}", added


async def bump_revision(
    db: AsyncSession, changed_entry_id: str | None, change_type: str, created_by: str | None,
) -> None:
    """Adds one DictionaryRevision row in the caller's open transaction —
    통합 설계서 §4.8/§5. Caller commits; this only stages the row so it lands
    in the same commit as the dictionary_entries write it's recording."""
    db.add(DictionaryRevision(
        changed_entry_id=changed_entry_id, change_type=change_type, created_by=created_by,
    ))


async def current_dictionary_version(db: AsyncSession) -> int | None:
    """The global dictionary_revisions version to pin on a new WorkflowRun —
    None means the dictionary has never been written to (사전 블록은 이 경우
    컷오프 없이 전체 enabled 항목을 그대로 읽는다, §5)."""
    return await db.scalar(select(func.max(DictionaryRevision.version)))
