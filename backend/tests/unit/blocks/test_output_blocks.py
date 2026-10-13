"""output_blocks: 후처리/출력 블록 테스트 (DB·Qdrant 경계는 모킹)."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.pipeline.blocks import output_blocks as ob
from app.pipeline.blocks.base import BlockContext


def _ctx(upstreams, config=None, document_id="doc-1", run_id="run-1"):
    return BlockContext(
        run_id=run_id, block_instance_id="b", document_id=document_id,
        upstream_outputs=upstreams, config=config or {},
    )


def _doc(**kw):
    base = dict(
        id="doc-1", summary=None, summary_status=None, suggested_tags=None, tags=[],
        category=None, metadata_status=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _run_output(upstreams, doc, chunks=None, config=None, index=None, **ctx_kw):
    db = MagicMock()
    db.get.return_value = doc
    db.query.return_value.filter.return_value.all.return_value = chunks or []
    index = index or MagicMock()
    with patch("app.db.session.get_sync_db", return_value=db), \
            patch("app.services.summary_index.index_document_summary", index):
        result = ob.OutputBlock().run(_ctx(upstreams, config, **ctx_kw))
    return result, db, index


# ---- 헬퍼 ----
def test_match_chunk_keywords_case_insensitive_keeps_original_case():
    assert ob._match_chunk_keywords("We use Python daily", ["python", "Java"]) == ["python"]


def test_match_chunk_keywords_ignores_blank_and_non_string():
    assert ob._match_chunk_keywords("abc", ["", "  ", None, 3, "ab"]) == ["ab"]


def test_dedup_strips_blank_and_case_duplicates():
    assert ob._dedup([" A ", "a", "", "  ", "B", 3, "3"]) == ["A", "B", "3"]


# ---- PostprocessBlock ----
def test_postprocess_strips_summary_leadin_and_whitespace():
    out = {"summary": "요약: 첫째   문장.\t둘째"}
    result = ob.PostprocessBlock().run(_ctx({"u": out}))
    assert result.output["summary"] == "첫째 문장. 둘째"


def test_postprocess_strips_polite_intro_sentence():
    out = {"summary": "다음은 문서의 요약입니다.\n본문 내용"}
    result = ob.PostprocessBlock().run(_ctx({"u": out}))
    assert result.output["summary"] == "본문 내용"


def test_postprocess_dedups_list_keys_only():
    out = {"keywords": ["a", "A", "b"], "entities": ["x", " x "], "problems": [], "tags": ["t", "t"]}
    result = ob.PostprocessBlock().run(_ctx({"u": out}))
    assert result.output["keywords"] == ["a", "b"]
    assert result.output["entities"] == ["x"]
    assert result.output["tags"] == ["t", "t"]


def test_postprocess_without_upstream_is_empty():
    assert ob.PostprocessBlock().run(_ctx({})).output == {}


def test_postprocess_does_not_mutate_upstream():
    out = {"keywords": ["a", "a"]}
    ob.PostprocessBlock().run(_ctx({"u": out}))
    assert out["keywords"] == ["a", "a"]


# ---- OutputBlock ----
def test_output_writes_summary_tags_category_and_indexes():
    doc = _doc(tags=["기존"])
    up = {"summary": " 요약 ", "keywords": ["기존", "에너지"], "entities": ["서울"], "category": "보고서", "text": "t"}
    result, db, index = _run_output({"u": up}, doc)
    assert doc.summary == "요약" and doc.summary_status == "DONE"
    assert doc.category == "보고서"
    assert doc.suggested_tags == ["에너지", "서울", "보고서"]
    assert doc.metadata_status == "DONE"
    assert "text" not in result.output
    assert result.output["saved_to_document"] == ["summary", "category", "suggested_tags"]
    fields = [c["field"] for c in result.output["changes"]]
    assert fields == ["summary", "suggested_tags"]
    db.commit.assert_called_once()
    db.close.assert_called_once()
    index.assert_called_once_with("doc-1", "요약")


def test_output_does_not_overwrite_user_edited_category():
    doc = _doc(category="내가 정한 분류", user_edited_fields=["category"])
    result, _, _ = _run_output({"u": {"category": "보고서", "keywords": ["에너지"]}}, doc)
    assert doc.category == "내가 정한 분류"
    assert "category" not in result.output["saved_to_document"]


def test_output_overwrites_category_when_only_other_fields_were_edited():
    doc = _doc(category="낡은 분류", user_edited_fields=["title"])
    _run_output({"u": {"category": "공고문"}}, doc)
    assert doc.category == "공고문"


def test_output_truncates_category_to_50_chars():
    doc = _doc()
    _run_output({"u": {"category": "가" * 80}}, doc)
    assert len(doc.category) == 50


def test_output_suggested_tags_none_when_all_already_tags():
    doc = _doc(tags=["A"], suggested_tags=None)
    _run_output({"u": {"keywords": ["a"]}}, doc)
    assert doc.suggested_tags is None


def test_output_merges_multiple_branches():
    ups = {
        "a": {"keywords": ["k1"], "summary": "", "category": "x"},
        "b": {"keywords": ["k1", "k2"], "summary": "요약", "category": "y"},
    }
    doc = _doc()
    result, _, _ = _run_output(ups, doc)
    assert doc.summary == "요약"
    assert doc.category == "x"
    assert result.output["keywords"] == ["k1", "k2"]


def test_output_back_propagates_keywords_to_child_chunks():
    chunks = [
        SimpleNamespace(chunk_text="에너지 절감", keywords=None),
        SimpleNamespace(chunk_text="무관한 내용", keywords=None),
    ]
    doc = _doc()
    result, db, _ = _run_output({"u": {"keywords": ["에너지", "  ", 5]}}, doc, chunks=chunks)
    assert chunks[0].keywords == ["에너지"]
    assert chunks[1].keywords is None
    assert "chunk_keywords" in result.output["saved_to_document"]


def test_output_skips_chunk_query_without_run_id():
    doc = _doc()
    _, db, _ = _run_output({"u": {"keywords": ["k"]}}, doc, run_id="")
    db.query.assert_not_called()


def test_output_no_chunks_means_no_chunk_keywords_field():
    result, _, _ = _run_output({"u": {"keywords": ["k"]}}, _doc(), chunks=[])
    assert "chunk_keywords" not in result.output["saved_to_document"]


def test_output_summary_index_failure_does_not_fail_run():
    index = MagicMock(side_effect=RuntimeError("qdrant down"))
    doc = _doc()
    result, db, _ = _run_output({"u": {"summary": "요약"}}, doc, index=index)
    assert result.output["saved_to_document"] == ["summary"]
    db.commit.assert_called_once()


def test_output_no_commit_or_index_when_nothing_to_save():
    result, db, index = _run_output({"u": {"foo": "bar"}}, _doc())
    db.commit.assert_not_called()
    index.assert_not_called()
    assert result.output["saved_to_document"] == []
    assert result.output["foo"] == "bar"


def test_output_missing_document_is_noop():
    result, db, _ = _run_output({"u": {"summary": "s"}}, None)
    db.commit.assert_not_called()
    db.close.assert_called_once()
    assert result.output["saved_to_document"] == []


def test_output_save_to_document_false_skips_db():
    with patch("app.db.session.get_sync_db") as getter:
        result = ob.OutputBlock().run(_ctx({"u": {"summary": "s"}}, {"save_to_document": False}))
    getter.assert_not_called()
    assert result.output["summary"] == "s"


def test_output_without_document_id_skips_db():
    with patch("app.db.session.get_sync_db") as getter:
        result = ob.OutputBlock().run(_ctx({"u": {"summary": "s"}}, document_id=None))
    getter.assert_not_called()
    assert result.output["changes"] == []


def test_output_change_records_before_values():
    doc = _doc(summary="이전 요약", suggested_tags=["old"])
    result, _, _ = _run_output({"u": {"summary": "새 요약", "keywords": ["new"]}}, doc)
    by_field = {c["field"]: c for c in result.output["changes"]}
    assert by_field["summary"]["before"] == "이전 요약"
    assert by_field["suggested_tags"]["before"] == ["old"]
    assert by_field["suggested_tags"]["after"] == ["old", "new"]


def test_output_closes_db_when_commit_fails():
    db = MagicMock()
    db.get.return_value = _doc()
    db.commit.side_effect = RuntimeError("x")
    with patch("app.db.session.get_sync_db", return_value=db):
        try:
            ob.OutputBlock().run(_ctx({"u": {"summary": "s"}}))
        except RuntimeError:
            pass
    db.close.assert_called_once()


def test_block_metadata():
    out, post = ob.OutputBlock(), ob.PostprocessBlock()
    assert out.block_type == "output" and post.block_type == "postprocess"
    assert out.block_version == "1.6.0"
    assert out.config_schema is ob.OutputConfig
    assert post.config_schema is None
    assert out.category == post.category == "분석"
