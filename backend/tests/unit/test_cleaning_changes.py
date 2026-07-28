"""Unit coverage for _resolve_cleaning_rule_name — built-in cleaning rules
(text_clean's collapse_whitespace, normalize_unicode, etc.) carry no
CleaningRule row, so their rule_name join is always NULL and the raw English
rule_key ("builtin:whitespace") used to leak straight to the UI (사용자 확인
2026-07-23, "정제비교에서 규칙이 다 영어야")."""
from app.api.v1.endpoints.documents import _resolve_cleaning_rule_name


def test_prefers_custom_rule_name_when_present():
    assert _resolve_cleaning_rule_name("전화번호 마스킹", "rule:abc123") == "전화번호 마스킹"


def test_maps_known_builtin_rule_key_to_korean_label():
    assert _resolve_cleaning_rule_name(None, "builtin:whitespace") == "공백·빈 줄 정리"
    assert _resolve_cleaning_rule_name(None, "builtin:unicode_nfc") == "유니코드 정규화(NFC)"


def test_falls_back_to_raw_rule_key_when_unrecognized():
    assert _resolve_cleaning_rule_name(None, "builtin:something_new") == "builtin:something_new"


def test_returns_none_when_neither_name_nor_key_present():
    assert _resolve_cleaning_rule_name(None, None) is None
