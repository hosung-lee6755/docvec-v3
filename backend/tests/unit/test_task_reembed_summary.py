"""Coverage for the reembed_collection, generate_summary and update_chunk_text
Celery tasks. DB sessions, embedding provider, Qdrant and LLM are mocked."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.pipeline.tasks import chunks as chunks_task
from app.pipeline.tasks import reembed, summary

# ---------------------------------------------------------------- reembed


def _collection():
    return SimpleNamespace(reembed_status=None, reembed_progress=None)


def _docs(*names):
    return [SimpleNamespace(id=f"id-{n}", original_filename=n) for n in names]


def _run_reembed(collection, docs, *, scroll, provider=None, db_get_side_effect=None):
    db = MagicMock()
    db.get.return_value = collection
    if db_get_side_effect is not None:
        db.get.side_effect = db_get_side_effect
    db.query.return_value.filter.return_value.all.return_value = docs
    provider = provider or MagicMock()
    if not isinstance(provider.embed, MagicMock) or provider.embed.side_effect is None:
        provider.embed.side_effect = lambda texts: [[float(i)] for i, _ in enumerate(texts)]
    qdrant = MagicMock()
    qdrant.scroll_by_document.side_effect = scroll
    job_log = {"fail": MagicMock(), "complete": MagicMock()}
    with patch("app.db.session.get_sync_db", return_value=db), \
         patch("app.pipeline.job_tracker.start_job", return_value="job"), \
         patch("app.pipeline.job_tracker.complete_job", job_log["complete"]), \
         patch("app.pipeline.job_tracker.fail_job", job_log["fail"]), \
         patch("app.services.embedding.get_embedding_provider", return_value=provider) as getter, \
         patch("app.services.qdrant_service.qdrant_service", qdrant):
        result = reembed.reembed_collection.run("c1", "new-model")
    return SimpleNamespace(result=result, db=db, qdrant=qdrant, provider=provider,
                           jobs=job_log, getter=getter)


def _hits(*texts):
    return [{"id": f"p{i}", "payload": {"text": t, "tags": ["x"]}} for i, t in enumerate(texts)]


def test_reembed_returns_not_found_for_unknown_collection():
    out = _run_reembed(None, [], scroll=lambda _id: [])

    assert out.result == {"collection_id": "c1", "status": "NOT_FOUND"}
    out.db.close.assert_called_once()


def test_reembed_replaces_vectors_but_preserves_ids_and_payload():
    coll = _collection()
    out = _run_reembed(coll, _docs("a.pdf"), scroll=lambda _id: _hits("첫째", "둘째"))

    points = out.qdrant.upsert_points.call_args.args[1]
    assert [p["id"] for p in points] == ["p0", "p1"]
    assert points[0]["payload"] == {"text": "첫째", "tags": ["x"]}
    assert [p["vector"] for p in points] == [[0.0], [1.0]]
    out.getter.assert_called_once_with("new-model")
    assert coll.reembed_status == "COMPLETED"
    assert out.result == {"collection_id": "c1", "status": "COMPLETED", "total": 1, "failed": []}


def test_reembed_document_without_chunks_completes_job_without_upsert():
    out = _run_reembed(_collection(), _docs("a.pdf"), scroll=lambda _id: [])

    out.qdrant.upsert_points.assert_not_called()
    out.jobs["complete"].assert_called_once()
    assert "0개 청크" in out.jobs["complete"].call_args.args[2]


def test_reembed_empty_collection_completes_with_zero_total():
    coll = _collection()
    out = _run_reembed(coll, [], scroll=lambda _id: [])

    assert coll.reembed_status == "COMPLETED"
    assert out.result["total"] == 0


def test_reembed_continues_past_failed_document_and_reports_failures():
    coll = _collection()

    def scroll(doc_id):
        if doc_id == "id-bad.pdf":
            raise RuntimeError("qdrant timeout")
        return _hits("ok")

    out = _run_reembed(coll, _docs("good.pdf", "bad.pdf", "good2.pdf"), scroll=scroll)

    assert coll.reembed_status == "FAILED"
    assert coll.reembed_progress == "2/3 완료, 1개 실패: bad.pdf"
    assert out.result["failed"] == ["bad.pdf"]
    out.jobs["fail"].assert_called_once()
    assert out.jobs["fail"].call_args.args[2] == "qdrant timeout"
    assert out.qdrant.upsert_points.call_count == 2  # the other two still re-embedded


def test_reembed_failure_summary_lists_at_most_five_filenames():
    names = [f"f{i}.pdf" for i in range(7)]
    coll = _collection()

    _run_reembed(coll, _docs(*names), scroll=MagicMock(side_effect=RuntimeError("x")))

    assert coll.reembed_progress.endswith("f0.pdf, f1.pdf, f2.pdf, f3.pdf, f4.pdf")
    assert coll.reembed_progress.startswith("0/7 완료, 7개 실패")


def test_reembed_model_load_error_marks_collection_failed():
    coll = _collection()
    docs = _docs("a.pdf")

    db = MagicMock()
    db.get.return_value = coll
    db.query.return_value.filter.return_value.all.return_value = docs
    with patch("app.db.session.get_sync_db", return_value=db), \
         patch("app.services.embedding.get_embedding_provider",
               side_effect=RuntimeError("m" * 80)), \
         patch("app.services.qdrant_service.qdrant_service", MagicMock()):
        result = reembed.reembed_collection.run("c1", "bad-model")

    assert result["status"] == "FAILED"
    assert coll.reembed_status == "FAILED"
    assert coll.reembed_progress == "m" * 50
    db.close.assert_called_once()


def test_reembed_survives_failure_state_recording_error():
    db = MagicMock()
    db.get.side_effect = [_collection(), RuntimeError("db gone")]
    db.query.side_effect = RuntimeError("query failed")

    with patch("app.db.session.get_sync_db", return_value=db):
        result = reembed.reembed_collection.run("c1", "m")

    assert result["status"] == "FAILED"
    assert "query failed" in result["error"]


# ---------------------------------------------------------------- summary


def _summary_doc(text="문서 본문"):
    return SimpleNamespace(parsed_text=text, summary=None, summary_status="PENDING")


def _run_summary(doc, generated, *, index_side_effect=None):
    db = MagicMock()
    db.get.return_value = doc
    provider = MagicMock()
    provider.generate.side_effect = generated if isinstance(generated, list) else [generated]
    index = MagicMock(side_effect=index_side_effect)
    with patch("app.db.session.get_sync_db", return_value=db), \
         patch("app.services.llm.get_llm_provider", return_value=provider) as getter, \
         patch("app.services.summary_index.index_document_summary", index):
        result = summary.generate_summary("doc-1")
    return SimpleNamespace(result=result, db=db, provider=provider, index=index, getter=getter)


@pytest.mark.parametrize(
    "text,expected",
    [("", 0.0), ("  \n ", 0.0), ("한글만", 0.0), ("漢字", 1.0), ("한漢", 0.5)],
)
def test_han_ratio(text, expected):
    assert summary._han_ratio(text) == expected


def test_summary_not_found():
    db = MagicMock()
    db.get.return_value = None
    with patch("app.db.session.get_sync_db", return_value=db):
        assert summary.generate_summary("x") == {"document_id": "x", "status": "NOT_FOUND"}


def test_summary_empty_text_marks_failed_without_calling_llm():
    doc = _summary_doc("   ")
    doc.summary = "stale"

    out = _run_summary(doc, "unused")

    assert out.result["status"] == "FAILED"
    assert out.result["reason"] == "empty text"
    assert doc.summary is None and doc.summary_status == "FAILED"
    out.provider.generate.assert_not_called()


def test_summary_stores_stripped_text_and_indexes_it():
    doc = _summary_doc()

    out = _run_summary(doc, "  요약 결과입니다.  ")

    assert out.result == {"document_id": "doc-1", "status": "DONE"}
    assert doc.summary == "요약 결과입니다."
    assert doc.summary_status == "DONE"
    out.index.assert_called_once()
    assert out.index.call_args.args == ("doc-1", "요약 결과입니다.")
    # v3: 요약 포인트에도 권한 사본을 싣는다(없으면 권한 필터에 걸려 검색되지 않음)
    assert {"sec_rank", "acl", "owner_id"} <= set(out.index.call_args.kwargs["access_fields"])
    out.getter.assert_called_once_with(summary._SUMMARY_MODEL_KEY)


def test_summary_truncates_input_to_context_budget():
    doc = _summary_doc("가" * (summary._MAX_SUMMARY_INPUT_CHARS + 5000))

    out = _run_summary(doc, "요약")

    prompt = out.provider.generate.call_args.args[1][0]["content"]
    assert prompt.count("가") == summary._MAX_SUMMARY_INPUT_CHARS


def test_summary_retries_once_when_output_drifts_to_chinese():
    doc = _summary_doc()

    out = _run_summary(doc, ["这是中文摘要内容完全没有韩文", "한국어 요약입니다"])

    assert doc.summary == "한국어 요약입니다"
    assert out.provider.generate.call_count == 2
    assert "중국어(한자) 사용 금지" in out.provider.generate.call_args.args[1][0]["content"]


def test_summary_index_failure_does_not_undo_stored_summary():
    doc = _summary_doc()

    out = _run_summary(doc, "요약", index_side_effect=RuntimeError("qdrant down"))

    assert out.result["status"] == "DONE"
    assert doc.summary_status == "DONE"


def test_summary_llm_failure_marks_document_failed_and_returns_error():
    doc = _summary_doc()

    out = _run_summary(doc, RuntimeError("model oom"))

    assert out.result["status"] == "FAILED"
    assert out.result["error"] == "model oom"
    assert doc.summary_status == "FAILED"
    out.db.rollback.assert_called_once()
    out.db.close.assert_called_once()


def test_summary_failure_recording_error_is_swallowed():
    db = MagicMock()
    db.get.side_effect = [_summary_doc(), RuntimeError("db gone")]
    provider = MagicMock()
    provider.generate.side_effect = RuntimeError("first")
    with patch("app.db.session.get_sync_db", return_value=db), \
         patch("app.services.llm.get_llm_provider", return_value=provider):
        result = summary.generate_summary("d")

    assert result["status"] == "FAILED" and result["error"] == "first"


# ------------------------------------------------------- update_chunk_text


def _run_update(existing, *, document_id="d1"):
    qdrant = MagicMock()
    qdrant.get_point.return_value = existing
    provider = MagicMock()
    provider.embed.return_value = [[0.5, 0.5]]
    with patch("app.services.qdrant_service.qdrant_service", qdrant), \
         patch("app.services.embedding.get_embedding_provider", return_value=provider):
        result = chunks_task.update_chunk_text.run(document_id, "p1", "새 본문")
    return result, qdrant, provider


def test_update_chunk_text_reembeds_and_marks_edited_keeping_payload():
    existing = {"id": "p1", "payload": {"document_id": "d1", "text": "old", "tags": ["t"]}}

    result, qdrant, provider = _run_update(existing)

    assert result == {"status": "OK", "point_id": "p1"}
    provider.embed.assert_called_once_with(["새 본문"])
    point = qdrant.upsert_points.call_args.args[1][0]
    assert point["id"] == "p1" and point["vector"] == [0.5, 0.5]
    assert point["payload"] == {"document_id": "d1", "text": "새 본문", "tags": ["t"], "edited": True}
    assert existing["payload"]["text"] == "old"  # input payload not mutated


def test_update_chunk_text_not_found_when_point_missing():
    result, qdrant, provider = _run_update(None)

    assert result == {"status": "NOT_FOUND", "point_id": "p1"}
    qdrant.upsert_points.assert_not_called()
    provider.embed.assert_not_called()


def test_update_chunk_text_refuses_point_belonging_to_other_document():
    existing = {"id": "p1", "payload": {"document_id": "other", "text": "x"}}

    result, qdrant, _provider = _run_update(existing, document_id="d1")

    assert result["status"] == "NOT_FOUND"
    qdrant.upsert_points.assert_not_called()
