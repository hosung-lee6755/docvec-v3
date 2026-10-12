"""quality_blocks: QualityCheckBlock.run 시나리오 및 판정 헬퍼 테스트 (DB 경계는 모킹)."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.pipeline.blocks import quality_blocks as qb
from app.pipeline.blocks.base import BlockContext

GOOD_TEXT = "가" * 200


def _doc(**kw):
    base = dict(
        id="doc-1", parsed_text=GOOD_TEXT, ocr_used=False, ocr_page_confidence=None,
        page_map=[], tables=None, quality_status=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _node(node_type, text="t"):
    return SimpleNamespace(node_type=node_type, text=text)


def _chunk(cid, size=300):
    return SimpleNamespace(id=cid, chunk_text="가" * size)


def _ctx(config=None, skip_review=False, document_id="doc-1"):
    return BlockContext(
        run_id="run-1", block_instance_id="b", document_id=document_id,
        upstream_outputs={"up": {"text": "x"}}, config=config or {}, skip_review=skip_review,
    )


class _Q:
    def __init__(self, **ends):
        self.ends = ends

    def __getattr__(self, name):
        if name in ("join", "filter"):
            return lambda *a, **k: self
        if name in self.ends:
            return lambda *a, **k: self.ends[name]
        raise AttributeError(name)


def _db(doc, nodes=(), chunks=(), step=None, report=None, app_count=0):
    db = MagicMock()
    db.get.return_value = doc
    by_model = {
        "WorkflowRunStep": _Q(first=step),
        "DocumentNode": _Q(all=list(nodes)),
        "DictionaryApplication": _Q(count=app_count),
        "DocumentChunk": _Q(all=list(chunks)),
        "QualityReport": _Q(one_or_none=report),
    }
    db.query.side_effect = lambda model: by_model[model.__name__]
    return db


def _run(doc, nodes=None, chunks=None, config=None, skip_review=False, **kw):
    default_nodes = [_node("HEADING"), _node("PARAGRAPH")]
    db = _db(
        doc,
        nodes=default_nodes if nodes is None else nodes,
        chunks=[_chunk("c1")] if chunks is None else chunks,
        **kw,
    )
    with patch("app.db.session.get_sync_db", return_value=db), \
            patch("app.pipeline.tasks.workflow._resolve_output", side_effect=lambda o: o or {}):
        result = qb.QualityCheckBlock().run(_ctx(config, skip_review))
    return result, db


# ---- 헬퍼 ----
def test_score_from_ratio_boundaries():
    assert qb._score_from_ratio(0, warn_above=0.1) == 100.0
    assert qb._score_from_ratio(-1, warn_above=0.1) == 100.0
    assert qb._score_from_ratio(0.1, warn_above=0.1) == 60.0
    assert qb._score_from_ratio(0.05, warn_above=0.1) == 80.0
    assert qb._score_from_ratio(0.15, warn_above=0.1) == pytest.approx(30.0)
    assert qb._score_from_ratio(0.5, warn_above=0.1) == 0.0
    assert qb._score_from_ratio(0.1, warn_above=0) == 0.0


def test_normalize_heading_like_strips_numbers_and_leaders():
    assert qb._normalize_heading_like("1.2 개요 ........ 15") == "개요"
    assert qb._normalize_heading_like("제3장 결과") == "결과"
    assert qb._normalize_heading_like(None) == ""


def test_determine_status_priority():
    base = dict(chunk_count=3, overall_score=90.0, fail_below_score=30.0,
                failed_pages=[], total_ocr_pages=0, has_warnings=False)
    assert qb._determine_status(**base) == "SUCCESS"
    assert qb._determine_status(**{**base, "has_warnings": True}) == "SUCCESS_WITH_WARNING"
    assert qb._determine_status(**{**base, "failed_pages": [2], "total_ocr_pages": 5}) == "PARTIAL_FAILURE"
    assert qb._determine_status(**{**base, "failed_pages": [1, 2], "total_ocr_pages": 2}) == "SUCCESS"
    assert qb._determine_status(**{**base, "overall_score": 10.0}) == "FAILURE"
    assert qb._determine_status(**{**base, "chunk_count": 0}) == "FAILURE"


@pytest.mark.parametrize("status,policy,skip,expected", [
    ("SUCCESS", "auto_pass", False, ("SUCCESS", False)),
    ("SUCCESS", "always_review", False, ("REVIEW_REQUIRED", True)),
    ("SUCCESS", "always_review", True, ("SUCCESS", False)),
    ("SUCCESS_WITH_WARNING", "review_on_warning", False, ("REVIEW_REQUIRED", True)),
    ("SUCCESS_WITH_WARNING", "auto_pass", False, ("SUCCESS_WITH_WARNING", False)),
    ("SUCCESS_WITH_WARNING", "always_review", True, ("SUCCESS_WITH_WARNING", False)),
    ("FAILURE", "auto_pass", True, ("FAILURE", True)),
    ("PARTIAL_FAILURE", "auto_pass", False, ("PARTIAL_FAILURE", True)),
])
def test_decide_review_matrix(status, policy, skip, expected):
    assert qb._decide_review(status, policy, skip) == expected


def test_toc_heading_match_ratio_none_without_toc():
    assert qb._toc_heading_match_ratio([], ["개요"]) is None


# ---- run ----
def test_run_requires_document_id():
    with pytest.raises(ValueError):
        qb.QualityCheckBlock().run(_ctx(document_id=None))


def test_run_missing_document_raises_and_closes_db():
    db = _db(None)
    with patch("app.db.session.get_sync_db", return_value=db):
        with pytest.raises(ValueError, match="찾을 수 없"):
            qb.QualityCheckBlock().run(_ctx())
    db.close.assert_called_once()


def test_run_healthy_document_is_success():
    doc = _doc()
    result, db = _run(doc, config={"review_policy": "auto_pass"})
    assert result.output["quality_status"] == "SUCCESS"
    assert result.output["overall_score"] == 100.0
    assert result.warnings == []
    assert result.requires_review is False
    assert doc.quality_status == "SUCCESS"
    assert result.metrics["chunk_count"] == 1
    db.add.assert_called_once()
    db.commit.assert_called_once()
    db.close.assert_called_once()


def test_run_default_policy_requires_review_on_warning():
    result, _ = _run(_doc(parsed_text="짧음"))
    assert result.output["quality_status"] == "REVIEW_REQUIRED"
    assert result.requires_review is True
    assert any("매우 짧습니다" in w for w in result.warnings)


def test_run_broken_characters_warning():
    result, _ = _run(_doc(parsed_text="가" * 100 + "�" * 20))
    assert any("깨진 문자" in w for w in result.warnings)
    assert result.metrics["broken_char_ratio"] > 0.05


def test_run_zero_chunks_forces_failure():
    result, _ = _run(_doc(), chunks=[])
    assert result.output["quality_status"] == "FAILURE"
    assert result.requires_review is True
    assert "생성된 청크가 없습니다." in result.warnings
    assert result.metrics["chunking"] == 0.0


def test_run_no_nodes_warns_structure_score_50():
    result, _ = _run(_doc(), nodes=[])
    assert result.metrics["structure"] == 50.0
    assert any("구조 분석 결과가 없습니다" in w for w in result.warnings)


def test_run_no_heading_warns():
    result, _ = _run(_doc(), nodes=[_node("PARAGRAPH")])
    assert any("제목이 하나도" in w for w in result.warnings)


def test_run_empty_pages_ratio_warning():
    doc = _doc(page_map=[[0, 1], [10, 5]])  # 5페이지 중 2페이지만 존재
    result, _ = _run(doc)
    assert result.metrics["empty_page_ratio"] == 0.6
    assert any("빈 페이지" in w for w in result.warnings)


def test_run_chunk_size_warnings_expose_ids():
    chunks = [_chunk("short", 5), _chunk("long", 3000), _chunk("ok", 300)]
    result, _ = _run(_doc(), chunks=chunks)
    assert result.metrics["short_chunk_ids"] == ["short"]
    assert result.metrics["long_chunk_ids"] == ["long"]
    assert any("너무 짧은" in w for w in result.warnings)
    assert any("너무 큰" in w for w in result.warnings)


def test_run_toc_heading_mismatch_warning():
    nodes = [_node("HEADING", "개요"), _node("PARAGRAPH"), _node("TOC", "1. 없는제목 .... 3")]
    result, _ = _run(_doc(), nodes=nodes)
    assert result.metrics["toc_heading_match_ratio"] == 0.0
    assert any("목차-제목" in w for w in result.warnings)


def test_run_toc_heading_match_ok():
    nodes = [_node("HEADING", "개요"), _node("PARAGRAPH"), _node("TOC", "1. 개요 .... 3")]
    result, _ = _run(_doc(), nodes=nodes, config={"review_policy": "auto_pass"})
    assert result.metrics["toc_heading_match_ratio"] == 1.0
    assert result.output["quality_status"] == "SUCCESS"


def test_run_implicit_tables_warning():
    tables = [{"detected_as": "implicit_alignment"}, {"detected_as": "ruled"}]
    result, _ = _run(_doc(tables=tables))
    assert result.metrics["implicit_table_ratio"] == 0.5
    assert any("암시적" in w for w in result.warnings)


def test_run_ocr_low_confidence_from_page_data():
    doc = _doc(ocr_used=True, ocr_page_confidence=[
        {"page_number": 1, "confidence": 0.9}, {"page_number": 2, "confidence": 0.2},
    ])
    result, _ = _run(doc, config={"review_policy": "auto_pass"})
    assert result.metrics["failed_pages"] == [2]
    assert result.output["quality_status"] == "PARTIAL_FAILURE"
    assert any("OCR 신뢰도가 낮은 페이지" in w for w in result.warnings)


def test_run_ocr_high_confidence_ok():
    doc = _doc(ocr_used=True, ocr_page_confidence=[{"page_number": 1, "confidence": 0.95}])
    result, _ = _run(doc, config={"review_policy": "auto_pass"})
    assert result.metrics["ocr"] == 100.0


def test_run_ocr_falls_back_to_format_detect_confidence():
    doc = _doc(ocr_used=True, ocr_page_confidence=[{"page_number": 1, "confidence": None}])
    step = SimpleNamespace(output={"confidence": 0.25})
    result, _ = _run(doc, step=step)
    assert result.metrics["ocr"] == 50.0
    assert any("OCR 신뢰도가 기준 이하" in w for w in result.warnings)


def test_run_ocr_unknown_confidence_scores_70():
    doc = _doc(ocr_used=True)
    result, _ = _run(doc, step=None)
    assert result.metrics["ocr"] == 70.0
    assert any("신뢰도 정보를 확인할 수 없습니다" in w for w in result.warnings)


def test_run_reuses_existing_report_row():
    report = SimpleNamespace(id="rep-1")
    result, db = _run(_doc(), report=report, config={"review_policy": "auto_pass"})
    db.add.assert_not_called()
    assert report.status == "SUCCESS"
    assert report.scores["chunking"] == 100.0
    assert result.output["quality_report_id"] == "rep-1"


def test_run_skip_review_downgrades_policy_but_not_failure():
    ok, _ = _run(_doc(parsed_text="짧음"), skip_review=True)
    assert ok.requires_review is False
    failed, _ = _run(_doc(), chunks=[], skip_review=True)
    assert failed.requires_review is True


def test_run_min_extraction_chars_zero_never_warns_short():
    result, _ = _run(_doc(parsed_text=""), config={"min_extraction_chars": 0})
    assert not any("매우 짧습니다" in w for w in result.warnings)


def test_run_carries_upstream_output():
    result, _ = _run(_doc())
    assert result.output["text"] == "x"


def test_block_metadata():
    block = qb.QualityCheckBlock()
    assert block.block_type == "quality_check"
    assert block.block_version == "1.5.0"
    assert block.category == "품질·제어"
    assert block.config_schema is qb.QualityCheckConfig
    with pytest.raises(Exception):
        qb.QualityCheckConfig(min_extraction_chars="abc")

# ---- 원문 재현율(sourceRecall) / 고정값 제외 ----
PDF_PAGE = "연간 점등시간은 3,200시간이며 전력 단가는 145.21원이다. 절감 전력은 정격 소비전력 기준이다."


def _pdf_doc(parsed_text):
    return _doc(parsed_text=parsed_text, mime_type="application/pdf", minio_key="k.pdf")


def test_normalization_is_not_scored_so_it_cannot_inflate_the_average():
    result, _ = _run(_doc(), config={"review_policy": "auto_pass"})
    assert "normalization" not in result.metrics
    assert set(result.metrics) >= {"textExtraction", "ocr", "structure", "chunking"}


def test_non_pdf_is_not_measured_and_reason_is_recorded():
    result, _ = _run(_doc(mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"))
    assert result.metrics["source_recall_status"] == "unsupported_format"
    assert result.metrics["source_recall"] is None
    assert "sourceRecall" not in result.metrics


def test_pdf_with_full_recall_scores_100_and_records_measurement():
    with patch.object(qb, "_load_pdf_page_texts", return_value=[PDF_PAGE]):
        result, _ = _run(_pdf_doc(PDF_PAGE * 3), config={"review_policy": "auto_pass"})
    assert result.metrics["source_recall_status"] == "measured"
    assert result.metrics["source_recall"] == 1.0
    assert result.metrics["sourceRecall"] == 100.0
    assert result.output["quality_status"] == "SUCCESS"


def test_pdf_with_missing_text_warns_lowers_score_and_lists_pages():
    parsed = "전혀 다른 내용이라서 원본 문장과 겹치지 않는 추출 결과입니다. " * 4
    with patch.object(qb, "_load_pdf_page_texts", return_value=[PDF_PAGE, PDF_PAGE]):
        result, _ = _run(_pdf_doc(parsed), config={"review_policy": "auto_pass"})
    assert result.metrics["sourceRecall"] < 60
    assert result.metrics["source_recall_low_pages"] == [1, 2]
    assert any("재현율이 낮습니다" in w for w in result.warnings)
    assert result.output["quality_status"] != "SUCCESS"
    assert result.output["overall_score"] < 100.0


def test_scanned_pdf_without_text_layer_is_not_measured():
    with patch.object(qb, "_load_pdf_page_texts", return_value=["", "", ""]):
        result, _ = _run(_pdf_doc(PDF_PAGE))
    assert result.metrics["source_recall_status"] == "no_text_layer"
    assert "sourceRecall" not in result.metrics


def test_unreadable_original_is_recorded_as_error_not_silently_skipped():
    with patch.object(qb, "_load_pdf_page_texts", side_effect=RuntimeError("minio down")):
        result, _ = _run(_pdf_doc(PDF_PAGE))
    assert result.metrics["source_recall_status"] == "error"
    assert "sourceRecall" not in result.metrics
