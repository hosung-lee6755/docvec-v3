"""normalization_blocks: 텍스트정제/불용어/동의어/사용자사전 블록 테스트 (DB 경계는 모킹)."""
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.pipeline.blocks import normalization_blocks as nb
from app.pipeline.blocks.base import BlockContext


def _ctx(text, config=None, extra=None, document_id="doc-1"):
    return BlockContext(
        run_id="r1", block_instance_id="b1", step_id="s1", document_id=document_id,
        upstream_outputs={"up": {"text": text, **(extra or {})}}, config=config or {},
    )


def _rule(rid, rtype, pattern, replacement=None):
    return SimpleNamespace(id=rid, rule_type=rtype, pattern=pattern, replacement=replacement)


def _entry(term, **kw):
    base = dict(
        id="e1", term=term, entry_type="x", match_type="EXACT", case_sensitive=False,
        scope=None, processing_mode="NORMALIZE", processing_rule="NORMALIZE",
        term_type="TERM", variants=[],
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _variant(term):
    return SimpleNamespace(variant_term=term)


def _db(rules=None, page_map=None, run_version=None):
    db = MagicMock()
    doc = SimpleNamespace(page_map=page_map)
    run = SimpleNamespace(dictionary_version=run_version)
    db.get.side_effect = lambda model, _id: doc if model.__name__ == "Document" else run
    db.query.return_value.filter.return_value.order_by.return_value.all.return_value = rules or []
    return db


def _clean(text, config=None, rules=None, page_map=None):
    db = _db(rules, page_map)
    with patch("app.db.session.get_sync_db", return_value=db):
        result = nb.TextCleanBlock().run(_ctx(text, config))
    return result, db


def _added(db):
    return [c.args[0] for c in db.add.call_args_list]


# ---- 순수 헬퍼 ----
def test_find_spans_match_types():
    text = "Cat concat cat."
    assert nb._find_spans("cat", "EXACT", False, text) == [(0, 3), (11, 14)]
    assert nb._find_spans("cat", "PREFIX", False, text) == [(0, 3), (11, 14)]
    assert nb._find_spans("cat", "SUFFIX", False, text) == [(0, 3), (7, 10), (11, 14)]
    assert len(nb._find_spans("cat", "CONTAINS", False, text)) == 3
    assert nb._find_spans("c.t", "REGEX", False, "cat cut") == [(0, 3), (4, 7)]


def test_find_spans_case_sensitivity_and_invalid_regex():
    assert nb._find_spans("cat", "EXACT", True, "Cat cat") == [(4, 7)]
    assert nb._find_spans("(", "REGEX", False, "abc") == []


def test_find_spans_korean_particle_still_matches_exact():
    assert nb._find_spans("김민준", "EXACT", False, "김민준님께서") == [(0, 3)]


def test_remove_spans_back_to_front():
    assert nb._remove_spans("abcdefg", [(0, 1), (3, 5)]) == "bcfg"
    assert nb._remove_spans("abc", []) == "abc"


def test_diff_sample_centers_on_first_difference():
    before = "a" * 500 + "X" + "b" * 500
    after = "a" * 500 + "Y" + "b" * 500
    b, a = nb._diff_sample(before, after, window=10)
    assert b == "a" * 10 + "X" + "b" * 9
    assert a == "a" * 10 + "Y" + "b" * 9


def test_diff_sample_when_after_is_prefix():
    b, a = nb._diff_sample("abc", "ab", window=100)
    assert (b, a) == ("abc", "ab")


def test_merged_protected_spans():
    ctx = _ctx("t", extra={"protected_spans": [[1, 2]]})
    assert nb._merged_protected_spans(ctx) == [(1, 2)]
    assert nb._merged_protected_spans(_ctx("t")) == []


def test_dictionary_version_cutoff():
    created = datetime(2026, 1, 1)
    db = MagicMock()
    db.get.return_value = SimpleNamespace(created_at=created)
    assert nb._dictionary_version_cutoff(db, None) is None
    assert nb._dictionary_version_cutoff(db, 5) == created
    db.get.return_value = None
    assert nb._dictionary_version_cutoff(db, 5) is None


def test_load_entries_as_of_applies_cutoff_only_when_given():
    db = MagicMock()
    query = db.query.return_value.filter.return_value.options.return_value
    query.filter.return_value.all.return_value = ["with_cutoff"]
    query.all.return_value = ["no_cutoff"]
    assert nb._load_entries_as_of(db, "stopword", datetime(2026, 1, 1)) == ["with_cutoff"]
    assert nb._load_entries_as_of(db, "stopword", None) == ["no_cutoff"]


# ---- TextCleanBlock ----
def test_text_clean_requires_document_id():
    with pytest.raises(ValueError):
        nb.TextCleanBlock().run(_ctx("텍스트", document_id=None))


def test_text_clean_builtins_normalize_and_record_changes():
    raw = "‘안녕’\x00  ＡＢＣ　１２３\n\n\n\n끝  "
    result, db = _clean(raw, {"apply_custom_rules": False})
    assert result.output["text"] == "'안녕' ABC 123\n\n끝"
    keys = {c.rule_key for c in _added(db) if hasattr(c, "rule_key")}
    assert {"builtin:control_chars", "builtin:quotes", "builtin:width", "builtin:whitespace"} <= keys
    revision = [o for o in _added(db) if getattr(o, "source", None) == "CLEAN"][0]
    assert revision.parsed_text == result.output["text"]
    assert result.metrics["changes_applied"] >= 4
    db.commit.assert_called_once()
    db.close.assert_called_once()


def test_text_clean_nfc_normalizes_decomposed_hangul():
    import unicodedata
    decomposed = unicodedata.normalize("NFD", "한글")
    result, _ = _clean(decomposed, {"apply_custom_rules": False})
    assert result.output["text"] == "한글"


def test_text_clean_no_change_records_no_changes():
    result, db = _clean("깨끗한 문장입니다.", {"apply_custom_rules": False})
    assert result.metrics["changes_applied"] == 0
    assert len(_added(db)) == 1  # 리비전 스냅샷만


def test_text_clean_all_builtins_disabled_keeps_text():
    cfg = {k: False for k in (
        "collapse_whitespace", "normalize_unicode", "normalize_quotes", "normalize_width",
        "remove_control_chars", "apply_custom_rules",
    )}
    result, _ = _clean("  ＡＢ  ", cfg)
    assert result.output["text"] == "  ＡＢ  "


def test_text_clean_ocr_fix_joins_hyphenated_lines():
    result, _ = _clean("exam-\nple", {"fix_ocr_errors": True, "apply_custom_rules": False})
    assert result.output["text"] == "example"


def test_text_clean_repeated_headers_removed_with_page_map():
    pages = ["머리글\n본문A\n", "머리글\n본문B\n", "머리글\n본문C\n", "머리글\n본문D\n"]
    text = "".join(pages)
    page_map, pos = [], 0
    for p in pages:
        pos += len(p)
        page_map.append([pos])
    cfg = {"remove_repeated_headers": True, "apply_custom_rules": False, "collapse_whitespace": False}
    result, db = _clean(text, cfg, page_map=page_map)
    assert "머리글" not in result.output["text"]
    assert "본문A" in result.output["text"]
    change = [c for c in _added(db) if getattr(c, "rule_key", None) == "builtin:repeated_headers"][0]
    assert change.change_count == 4


def test_text_clean_repeated_headers_noop_without_enough_pages():
    cfg = {"remove_repeated_headers": True, "apply_custom_rules": False, "collapse_whitespace": False}
    result, _ = _clean("머리글\n본문", cfg, page_map=[[3]])
    assert "머리글" in result.output["text"]


def test_text_clean_repeated_headers_none_repeated():
    pages = ["가\n", "나\n", "다\n"]
    page_map, pos = [], 0
    for p in pages:
        pos += len(p)
        page_map.append([pos])
    cfg = {"remove_repeated_headers": True, "apply_custom_rules": False, "collapse_whitespace": False}
    result, _ = _clean("".join(pages), cfg, page_map=page_map)
    assert result.output["text"] == "가\n나\n다\n"


def test_text_clean_custom_rules_all_types():
    rules = [
        _rule("r1", "REGEX_REPLACE", r"\d{3}", "###"),
        _rule("r2", "EXACT_REMOVE", "[광고]"),
        _rule("r3", "LINE_FILTER", r"^페이지 \d+$"),
    ]
    text = "코드 123 본문[광고]\n페이지 7\n마지막"
    result, db = _clean(text, {"collapse_whitespace": False}, rules=rules)
    assert result.output["text"] == "코드 ### 본문\n마지막"
    changes = [c for c in _added(db) if getattr(c, "rule_id", None)]
    assert {c.rule_id for c in changes} == {"r1", "r2", "r3"}
    assert all(c.rule_key is None for c in changes)
    exact = [c for c in changes if c.rule_id == "r2"][0]
    assert exact.sample_matches and "[광고]" in exact.sample_matches[0]


def test_text_clean_regex_replace_without_replacement_removes_match():
    result, _ = _clean("a1b2", {"collapse_whitespace": False}, rules=[_rule("r1", "REGEX_REPLACE", r"\d")])
    assert result.output["text"] == "ab"


def test_text_clean_skips_invalid_regex_and_patternless_rules():
    rules = [
        _rule("r1", "REGEX_REPLACE", "("),
        _rule("r2", "LINE_FILTER", "("),
        _rule("r3", "EXACT_REMOVE", None),
        _rule("r4", "UNKNOWN", "x"),
    ]
    result, _ = _clean("x 본문", {"collapse_whitespace": False}, rules=rules)
    assert result.output["text"] == "x 본문"


def test_text_clean_carries_upstream_keys():
    ctx = _ctx("텍스트", {"apply_custom_rules": False}, extra={"title": "T"})
    db = _db()
    with patch("app.db.session.get_sync_db", return_value=db):
        result = nb.TextCleanBlock().run(ctx)
    assert result.output["title"] == "T"


def test_text_clean_closes_db_on_error():
    db = _db()
    db.commit.side_effect = RuntimeError("x")
    with patch("app.db.session.get_sync_db", return_value=db):
        with pytest.raises(RuntimeError):
            nb.TextCleanBlock().run(_ctx("텍스트", {"apply_custom_rules": False}))
    db.close.assert_called_once()


# ---- Stopword / Synonym / UserDict ----
def _run_dict(block, ctx, entries, run=SimpleNamespace(dictionary_version=2)):
    db = MagicMock()
    db.get.return_value = run
    with patch("app.db.session.get_sync_db", return_value=db), \
            patch.object(nb, "_dictionary_version_cutoff", return_value=None), \
            patch.object(nb, "_load_entries_as_of", return_value=entries):
        return block().run(ctx), db


@pytest.mark.parametrize("block", [nb.StopwordBlock, nb.SynonymBlock, nb.UserDictBlock])
def test_dict_blocks_require_document_id(block):
    with pytest.raises(ValueError):
        block().run(_ctx("텍스트", document_id=None))


def test_stopword_mark_does_not_modify_text_but_records():
    result, db = _run_dict(nb.StopwordBlock, _ctx("그리고 본문"), [_entry("그리고")])
    assert result.output["text"] == "그리고 본문"
    assert result.metrics == {"stopword_matches": 1, "action": "mark"}
    app = _added(db)[0]
    assert (app.original_text, app.start_offset, app.end_offset) == ("그리고", 0, 3)
    assert app.dictionary_version == 2
    db.commit.assert_called_once()


def test_stopword_remove_action_strips_matches():
    result, _ = _run_dict(
        nb.StopwordBlock, _ctx("그리고 본문 그리고", {"action": "remove"}), [_entry("그리고")],
    )
    assert result.output["text"] == " 본문 "


def test_stopword_scope_filter():
    entries = [_entry("가", scope=["a"]), _entry("나", scope=["b"]), _entry("다", scope=None)]
    result, _ = _run_dict(
        nb.StopwordBlock, _ctx("가 나 다", {"scope_filter": ["b"]}), entries,
    )
    assert result.metrics["stopword_matches"] == 1


def test_stopword_skips_protected_spans():
    ctx = _ctx("그리고 본문", extra={"protected_spans": [[0, 3]]})
    result, db = _run_dict(nb.StopwordBlock, ctx, [_entry("그리고")])
    assert result.metrics["stopword_matches"] == 0
    assert _added(db) == []


def test_stopword_without_run_uses_version_zero():
    result, db = _run_dict(nb.StopwordBlock, _ctx("그리고"), [_entry("그리고")], run=None)
    assert _added(db)[0].dictionary_version == 0


def test_synonym_normalize_replaces_variant_with_standard_term():
    entry = _entry("인공지능", variants=[_variant("AI"), _variant("에이아이")])
    result, db = _run_dict(nb.SynonymBlock, _ctx("AI 와 에이아이 그리고 ai"), [entry])
    assert result.output["text"] == "인공지능 와 인공지능 그리고 인공지능"
    assert result.metrics["synonym_applications"] == 3
    assert all(a.normalized_text == "인공지능" for a in _added(db))


def test_synonym_replaces_variant_followed_by_korean_particle():
    # 조사가 공백 없이 붙어도(에이아이는, AI가) 기록만 남고 치환이 빠지면 안 된다
    entry = _entry("인공지능", variants=[_variant("AI"), _variant("에이아이")])
    result, db = _run_dict(nb.SynonymBlock, _ctx("에이아이는 AI가 바꾼다"), [entry])
    assert result.output["text"] == "인공지능는 인공지능가 바꾼다"
    assert result.metrics["synonym_applications"] == 2


def test_synonym_does_not_replace_inside_a_longer_word():
    # 앞쪽 경계는 지킨다: "MAIL" 안의 "AI"는 바꾸지 않는다
    entry = _entry("인공지능", variants=[_variant("AI")])
    result, _ = _run_dict(nb.SynonymBlock, _ctx("MAIL 서버"), [entry])
    assert result.output["text"] == "MAIL 서버"
    assert result.metrics["synonym_applications"] == 0


def test_user_dict_replaces_variant_followed_by_korean_particle():
    entry = _entry("한국에너지공단", variants=[_variant("에너지공단")])
    result, _ = _run_dict(nb.UserDictBlock, _ctx("에너지공단이 발표했다"), [entry])
    assert result.output["text"] == "한국에너지공단이 발표했다"


def test_synonym_tag_only_marks_without_replacing():
    entry = _entry("인공지능", variants=[_variant("AI")])
    result, db = _run_dict(nb.SynonymBlock, _ctx("AI 시대", {"processing_mode": "tag_only"}), [entry])
    assert result.output["text"] == "AI 시대"
    assert _added(db)[0].normalized_text is None


def test_synonym_entry_processing_mode_tag_not_replaced():
    entry = _entry("인공지능", processing_mode="TAG", variants=[_variant("AI")])
    result, _ = _run_dict(nb.SynonymBlock, _ctx("AI 시대"), [entry])
    assert result.output["text"] == "AI 시대"
    assert result.metrics["synonym_applications"] == 1


def test_synonym_no_variant_match():
    entry = _entry("인공지능", variants=[_variant("AI")])
    result, db = _run_dict(nb.SynonymBlock, _ctx("무관한 문장"), [entry])
    assert result.metrics["synonym_applications"] == 0
    assert _added(db) == []


def test_user_dict_protects_terms_and_normalizes_variants():
    entry = _entry("에너지공단", variants=[_variant("KEA")])
    result, db = _run_dict(nb.UserDictBlock, _ctx("에너지공단 와 KEA"), [entry])
    assert result.output["text"] == "에너지공단 와 에너지공단"
    assert result.metrics["user_dict_applications"] == 2
    assert [0, 5] in result.output["protected_spans"]


def test_user_dict_ignore_rule_and_term_type_filter():
    entries = [
        _entry("무시", processing_rule="IGNORE"),
        _entry("다른", term_type="PERSON"),
        _entry("대상", term_type="ORG"),
    ]
    result, _ = _run_dict(
        nb.UserDictBlock, _ctx("무시 다른 대상", {"term_types": ["ORG"]}), entries,
    )
    assert result.metrics["user_dict_applications"] == 1


def test_user_dict_keep_rule_skips_variants():
    entry = _entry("KEA", processing_rule="KEEP", variants=[_variant("케아")])
    result, _ = _run_dict(nb.UserDictBlock, _ctx("KEA 케아"), [entry])
    assert result.output["text"] == "KEA 케아"
    assert result.metrics["user_dict_applications"] == 1


def test_user_dict_other_rule_marks_variant_without_replacing():
    entry = _entry("KEA", processing_rule="TAG", variants=[_variant("케아")])
    result, db = _run_dict(nb.UserDictBlock, _ctx("케아"), [entry])
    assert result.output["text"] == "케아"
    assert _added(db)[0].normalized_text is None


def test_user_dict_merges_upstream_protected_spans():
    entry = _entry("KEA")
    ctx = _ctx("KEA", extra={"protected_spans": [[10, 12]]})
    result, _ = _run_dict(nb.UserDictBlock, ctx, [entry])
    assert result.output["protected_spans"][0] == [10, 12]
    assert [0, 3] in result.output["protected_spans"]


def test_user_dict_no_protection_when_disabled_or_no_matches():
    entry = _entry("KEA")
    off, _ = _run_dict(nb.UserDictBlock, _ctx("KEA", {"protect_from_stopwords": False}), [entry])
    none, _ = _run_dict(nb.UserDictBlock, _ctx("무관"), [entry])
    assert "protected_spans" not in off.output
    assert "protected_spans" not in none.output


# ---- 메타데이터 ----
@pytest.mark.parametrize("block,btype,schema", [
    (nb.TextCleanBlock, "text_clean", nb.TextCleanConfig),
    (nb.StopwordBlock, "stopword", nb.StopwordConfig),
    (nb.SynonymBlock, "synonym", nb.SynonymConfig),
    (nb.UserDictBlock, "user_dict", nb.UserDictConfig),
])
def test_block_metadata(block, btype, schema):
    instance = block()
    assert (instance.block_type, instance.config_schema) == (btype, schema)
    assert instance.category == "정제·정규화"


def test_text_clean_config_defaults():
    cfg = nb.TextCleanConfig()
    assert cfg.collapse_whitespace and not cfg.fix_ocr_errors
    with pytest.raises(Exception):
        nb.TextCleanConfig(collapse_whitespace="maybe")


# ---- v3 마일스톤 6: 문맥 기록, 문서별 끄기, 되돌리기 반영 ----
def _run_with_skips(block, ctx, entries, excluded=(), reverted=()):
    with patch.object(nb, "_document_dictionary_skips", return_value=(set(excluded), set(reverted))):
        return _run_dict(block, ctx, entries)


def test_applications_record_surrounding_context():
    text = "가" * 50 + " 그리고 " + "나" * 50
    _result, db = _run_dict(nb.StopwordBlock, _ctx(text), [_entry("그리고")])
    app = _added(db)[0]
    assert app.context_before == "가" * 39 + " " and app.context_after == " " + "나" * 39


@pytest.mark.parametrize("block, entry", [
    (nb.StopwordBlock, _entry("그리고", id="off")),
    (nb.SynonymBlock, _entry("인공지능", id="off", variants=[_variant("AI")])),
    (nb.UserDictBlock, _entry("인공지능", id="off", variants=[_variant("AI")])),
])
def test_entries_turned_off_for_the_document_are_skipped(block, entry):
    result, db = _run_with_skips(block, _ctx("그리고 AI 인공지능"), [entry], excluded={"off"})
    assert result.output["text"] == "그리고 AI 인공지능"
    assert _added(db) == []


def test_reverted_synonym_is_no_longer_replaced_but_others_are():
    entry = _entry("인공지능", id="e1", variants=[_variant("AI"), _variant("에이아이")])
    result, db = _run_with_skips(nb.SynonymBlock, _ctx("AI 와 에이아이"), [entry], reverted={("e1", "AI")})
    assert result.output["text"] == "AI 와 인공지능"
    assert [a.original_text for a in _added(db)] == ["에이아이"]


def test_reverted_stopword_occurrence_is_skipped():
    result, _db = _run_with_skips(nb.StopwordBlock, _ctx("그리고 본문 그리고"), [_entry("그리고", id="e1")],
                                  reverted={("e1", "그리고")})
    assert result.metrics["stopword_matches"] == 0



def test_application_context_masks_personal_data_even_across_the_window_edge():
    # 전화번호가 문맥 경계(앞 40자)에 걸쳐 있어도, 이메일이 뒤 문맥에 있어도 가린다
    text = "연락처 010-1234-5678 " + "가" * 30 + " 그리고 " + "이메일 hong@example.com 입니다"
    _result, db = _run_dict(nb.StopwordBlock, _ctx(text), [_entry("그리고")])
    app = _added(db)[0]
    assert "5678" not in app.context_before and "1234" not in app.context_before
    assert "hong@example.com" not in app.context_after and "*" in app.context_after
    # 가려도 길이는 그대로라 위치가 어긋나지 않는다
    assert len(app.context_before) == 40


def test_find_spans_latin_term_glued_to_korean_still_matches():
    # "\b"는 한글도 단어 글자로 봐서 "국가R&D"의 "R&D"를 놓쳤다. 앞 글자와 문자 체계가 다르면 경계로 본다.
    assert nb._find_spans("R&D", "EXACT", False, "국가R&D과제와 R&D") == [(2, 5), (9, 12)]
    assert nb._find_spans("반도체", "EXACT", False, "AI반도체") == [(2, 5)]


def test_find_spans_still_refuses_a_match_inside_a_longer_word_of_the_same_script():
    assert nb._find_spans("AI", "EXACT", False, "MAIL AI") == [(5, 7)]
    assert nb._find_spans("민국", "EXACT", False, "대한민국 민국") == [(5, 7)]
    assert nb._find_spans("v2", "PREFIX", False, "Av2 v2") == [(4, 6)]
