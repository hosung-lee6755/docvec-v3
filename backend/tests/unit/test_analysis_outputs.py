"""분석 워크플로우가 문서에 남기는 항목(요약, 태그, 분류) 판정과, 만들지 않는 항목 비우기(2026-11-20 사용자 지시).

사용자 워크플로우를 그대로 따른다. 요약 블록이 없는 워크플로우로 분석하면 예전 요약을 남기지 않고 비운다.
"""
from types import SimpleNamespace

from app.pipeline.analysis_outputs import (
    CATEGORY,
    SUMMARY,
    TAGS,
    analysis_outputs,
    clear_unproduced_fields,
)


def _doc(**overrides):
    base = {
        "summary": "예전 요약", "summary_status": "DONE", "suggested_tags": ["예전"], "metadata_status": "DONE",
        "category": "예전 분류", "user_edited_fields": None, "tags": ["사용자 태그"],
    }
    return SimpleNamespace(**{**base, **overrides})


def test_standard_chain_produces_everything():
    blocks = [("input", {}), ("summarize", {}), ("extract_keywords", {}), ("classify", {}), ("output", {})]
    assert analysis_outputs(blocks) == {SUMMARY, TAGS, CATEGORY}


def test_nothing_is_saved_without_an_output_block():
    assert analysis_outputs([("input", {}), ("summarize", {}), ("classify", {})]) == set()


def test_output_that_does_not_save_to_the_document_produces_nothing():
    blocks = [("summarize", {}), ("output", {"save_to_document": False})]
    assert analysis_outputs(blocks) == set()


def test_keywords_only_workflow_produces_tags_only():
    assert analysis_outputs([("input", {}), ("extract_keywords", {}), ("output", {})]) == {TAGS}


def test_entities_produce_tags():
    assert analysis_outputs([("extract_entities", {}), ("output", {})]) == {TAGS}


def test_classify_adds_the_category_to_tags_unless_turned_off():
    assert analysis_outputs([("classify", {}), ("output", {})]) == {CATEGORY, TAGS}
    assert analysis_outputs([("classify", {}), ("output", {"category_as_tag": False})]) == {CATEGORY}


def test_missing_config_counts_as_default():
    assert analysis_outputs([("summarize", None), ("output", None)]) == {SUMMARY}


def test_clearing_for_a_keywords_only_workflow_keeps_tags_and_clears_the_rest():
    doc = _doc()
    cleared = clear_unproduced_fields(doc, {TAGS})
    assert cleared == [SUMMARY, CATEGORY]
    assert doc.summary is None
    assert doc.summary_status == "SKIPPED"
    assert doc.category is None
    assert doc.suggested_tags == ["예전"]
    assert doc.metadata_status == "DONE"


def test_clearing_everything_marks_metadata_skipped_and_never_touches_user_tags():
    doc = _doc()
    cleared = clear_unproduced_fields(doc, set())
    assert cleared == [SUMMARY, TAGS, CATEGORY]
    assert doc.suggested_tags is None
    assert doc.metadata_status == "SKIPPED"
    assert doc.tags == ["사용자 태그"]


def test_user_edited_category_is_kept():
    doc = _doc(user_edited_fields=["category"])
    cleared = clear_unproduced_fields(doc, {SUMMARY})
    assert CATEGORY not in cleared
    assert doc.category == "예전 분류"


def test_produced_fields_are_left_for_the_run_to_overwrite():
    doc = _doc()
    assert clear_unproduced_fields(doc, {SUMMARY, TAGS, CATEGORY}) == []
    assert doc.summary == "예전 요약"
    assert doc.summary_status == "DONE"
