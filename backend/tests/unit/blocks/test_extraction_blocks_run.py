"""extraction_blocks: FileValidate/FormatDetect/TextExtract/Ocr 블록 테스트 (어댑터·스토리지·DB 모킹)."""
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from pathlib import Path

import pytest

from app.pipeline.adapters import UnsupportedFileTypeError
from app.pipeline.blocks import extraction_blocks as eb
from app.pipeline.blocks.base import BlockContext, BlockExecutionError

MB = 1024 * 1024


def _ctx(config=None, document_id="doc-1", upstream=None):
    return BlockContext(
        run_id="r1", block_instance_id="b", document_id=document_id,
        upstream_outputs={"up": upstream} if upstream is not None else {}, config=config or {},
    )


def _doc(**kw):
    base = dict(
        id="doc-1", filename="보고서.PDF", file_size=1 * MB, file_hash="h", collection_id="c1",
        minio_key="k", mime_type="application/pdf", parsed_text=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


# ---- FileValidateBlock ----
def _validate(doc, config=None, dup=None):
    db = MagicMock()
    db.get.return_value = doc
    db.query.return_value.filter.return_value.first.return_value = dup
    with patch("app.db.session.get_sync_db", return_value=db):
        result = eb.FileValidateBlock().run(_ctx(config))
    return result, db


def test_file_validate_requires_document_id():
    with pytest.raises(ValueError):
        eb.FileValidateBlock().run(_ctx(document_id=None))


def test_file_validate_missing_document_closes_db():
    db = MagicMock()
    db.get.return_value = None
    with patch("app.db.session.get_sync_db", return_value=db):
        with pytest.raises(ValueError, match="찾을 수 없"):
            eb.FileValidateBlock().run(_ctx())
    db.close.assert_called_once()


def test_file_validate_passes_and_reports_checks():
    result, db = _validate(_doc())
    names = [c["name"] for c in result.output["checks"]]
    assert names == ["extension", "file_size", "duplicate"]
    assert result.output["passed"] is True
    assert result.output["document_id"] == "doc-1"
    db.close.assert_called_once()


def test_file_validate_extension_comparison_is_case_insensitive():
    result, _ = _validate(_doc(filename="a.PdF"), {"allowed_extensions": [".PDF"]})
    assert result.output["checks"][0]["ok"] is True


def test_file_validate_rejects_unsupported_extension_permanently():
    with pytest.raises(BlockExecutionError) as exc:
        _validate(_doc(filename="a.exe"))
    assert exc.value.error_code == "FILE_UNSUPPORTED" and exc.value.permanent is True


def test_file_validate_rejects_missing_extension():
    with pytest.raises(BlockExecutionError, match="알 수 없음"):
        _validate(_doc(filename="README"))


def test_file_validate_rejects_oversized_file():
    with pytest.raises(BlockExecutionError, match="파일 크기 초과"):
        _validate(_doc(file_size=11 * MB), {"max_file_size_mb": 10})


def test_file_validate_boundary_size_is_allowed():
    result, _ = _validate(_doc(file_size=10 * MB), {"max_file_size_mb": 10})
    assert result.output["checks"][1]["ok"] is True


def test_file_validate_reports_duplicate_without_failing():
    result, _ = _validate(_doc(), dup=SimpleNamespace(id="other"))
    dup = result.output["checks"][-1]
    assert dup == {"name": "duplicate", "ok": False, "detail": "other"}


def test_file_validate_skips_duplicate_check_when_disabled_and_adds_malware_placeholder():
    result, db = _validate(_doc(), {"reject_duplicates": False, "scan_malware": True})
    assert [c["name"] for c in result.output["checks"]] == ["extension", "file_size", "malware_scan"]
    db.query.assert_not_called()


# ---- _detect_pdf_signals ----
def _pdf_with_pages(texts):
    pdf = MagicMock()
    pdf.pages = [MagicMock(extract_text=MagicMock(return_value=t)) for t in texts]
    cm = MagicMock()
    cm.__enter__.return_value = pdf
    return cm


def test_detect_pdf_signals_text_layer_present():
    with patch("pdfplumber.open", return_value=_pdf_with_pages(["가" * 30])):
        assert eb._detect_pdf_signals("x.pdf") == (True, False, 1.0)


def test_detect_pdf_signals_scanned_gives_partial_confidence():
    with patch("pdfplumber.open", return_value=_pdf_with_pages([None, "가" * 10])):
        has_text, encrypted, confidence = eb._detect_pdf_signals("x.pdf")
    assert (has_text, encrypted) == (False, False)
    assert confidence == pytest.approx(0.1)


def test_detect_pdf_signals_only_samples_first_pages():
    texts = [""] * eb._PDF_SAMPLE_PAGES + ["가" * 100]
    with patch("pdfplumber.open", return_value=_pdf_with_pages(texts)):
        assert eb._detect_pdf_signals("x.pdf")[0] is False


@pytest.mark.parametrize("message", ["file requires a Password", "PDF is Encrypted"])
def test_detect_pdf_signals_encrypted(message):
    with patch("pdfplumber.open", side_effect=Exception(message)):
        assert eb._detect_pdf_signals("x.pdf") == (False, True, 0.0)


def test_detect_pdf_signals_unknown_error_is_neutral():
    with patch("pdfplumber.open", side_effect=Exception("corrupt")):
        assert eb._detect_pdf_signals("x.pdf") == (True, False, 0.5)


# ---- FormatDetectBlock ----
class DocxAdapter:
    pass


def _detect(doc, adapter=None, adapter_error=None, signals=None):
    db = MagicMock()
    db.get.return_value = doc
    storage = MagicMock()
    storage.download_file.return_value = b"bytes"
    getter = MagicMock(side_effect=adapter_error) if adapter_error else MagicMock(return_value=adapter)
    with patch("app.db.session.get_sync_db", return_value=db), \
            patch("app.services.storage.storage_service", storage), \
            patch("app.pipeline.adapters.get_adapter", getter), \
            patch.object(eb, "_detect_pdf_signals", return_value=signals or (True, False, 1.0)):
        result = eb.FormatDetectBlock().run(_ctx())
    return result, db


def test_format_detect_non_pdf_defaults_to_text_layer():
    result, db = _detect(_doc(filename="a.docx", mime_type="x"), adapter=DocxAdapter())
    assert result.output["detected_file_type"] == "docx"
    assert result.output["has_text_layer"] is True
    assert result.output["is_scanned_document"] is False
    assert result.output["confidence"] == 1.0
    db.close.assert_called_once()


def test_format_detect_pdf_scanned_signals_flow_through():
    result, _ = _detect(_doc(), adapter=DocxAdapter(), signals=(False, False, 0.2))
    assert result.output["is_scanned_document"] is True
    assert result.output["confidence"] == 0.2


def test_format_detect_encrypted_pdf_fails_permanently():
    with pytest.raises(BlockExecutionError) as exc:
        _detect(_doc(), adapter=DocxAdapter(), signals=(False, True, 0.0))
    assert exc.value.error_code == "FILE_ENCRYPTED" and exc.value.permanent


def test_format_detect_unsupported_adapter_maps_to_block_error():
    with pytest.raises(BlockExecutionError) as exc:
        _detect(_doc(filename="a.xyz"), adapter_error=UnsupportedFileTypeError(Path("a.xyz"), "x/y"))
    assert exc.value.error_code == "FILE_UNSUPPORTED"


def test_format_detect_missing_document():
    db = MagicMock()
    db.get.return_value = None
    with patch("app.db.session.get_sync_db", return_value=db):
        with pytest.raises(ValueError):
            eb.FormatDetectBlock().run(_ctx())
    db.close.assert_called_once()


# ---- 순수 헬퍼 ----
def test_strip_nul_bytes_recurses_into_containers():
    value = {"a": "x\x00y", "b": ["\x00", {"c": "ok"}], "d": 3}
    assert eb._strip_nul_bytes(value) == {"a": "xy", "b": ["", {"c": "ok"}], "d": 3}


def test_strip_nul_bytes_leaves_clean_values():
    assert eb._strip_nul_bytes("clean") == "clean"
    assert eb._strip_nul_bytes(None) is None


def test_strip_excluded_lines():
    assert eb._strip_excluded_lines("a\n머리글\nb", {"머리글"}) == "a\nb"
    assert eb._strip_excluded_lines("a\nb", set()) == "a\nb"


def _page(blocks, **kw):
    base = dict(
        page_number=1, height=800, text_blocks=blocks, table_candidates=[],
        ocr_confidence=None, ocr_word_count=0,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _block(text, element_id=None):
    return SimpleNamespace(text=text, element_id=element_id)


def test_assemble_full_text_offsets_match_joined_string():
    pages = [_page([_block("첫째", "e1"), _block("  ", "skip")]), _page([_block("둘\x00째", "e2")])]
    text, spans = eb._assemble_full_text(pages, set())
    assert text == "첫째\n\n둘째"
    assert spans == {"e1": (0, 2), "e2": (4, 6)}
    assert text[slice(*spans["e2"])] == "둘째"


def test_assemble_full_text_empty_pages():
    assert eb._assemble_full_text([], set()) == ("", {})


def test_match_image_paths_ignores_non_pictures_and_exhausts_candidates():
    elements = [
        {"type": "picture", "page": 1}, {"type": "picture", "page": 1},
        {"type": "text", "page": 1}, {"type": "picture", "page": 9},
    ]
    eb._match_image_paths(elements, [{"page_number": 1, "storage_key": "k1"}])
    assert elements[0]["metadata"]["image_path"] == "k1"
    assert "metadata" not in elements[1] and "metadata" not in elements[2] and "metadata" not in elements[3]


# ---- TextExtractBlock ----
def _parsed(**kw):
    page = _page(
        [_block("본문 텍스트입니다 안녕하세요", "e1")],
        table_candidates=[SimpleNamespace(rows=[["a"]], id="t1", confidence=0.9, detected_as="ruled")],
        ocr_confidence=0.8, ocr_word_count=5,
    )
    base = dict(
        format_id="pdf", pages=[page], page_count=1,
        metadata={
            "line_layout": [{"text": "x", "page_number": 1}],
            "elements": [{"id": "e1", "type": "text"}, {"id": "p", "type": "picture", "page": 1}],
            "ocr_used": True, "document_created_at": datetime(2026, 1, 1),
        },
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _extract(doc, parsed=None, config=None, adapter_error=None, extract_error=None, images=None, repaginate_error=None):
    db = MagicMock()
    db.get.return_value = doc
    adapter = MagicMock()
    if extract_error:
        adapter.extract.side_effect = extract_error
    else:
        adapter.extract.return_value = parsed or _parsed()
    getter = MagicMock(side_effect=adapter_error) if adapter_error else MagicMock(return_value=adapter)
    storage = MagicMock()
    storage.download_file.return_value = b"data"
    images_mock = MagicMock(return_value=images or [{"page_number": 1, "storage_key": "img1"}])
    if isinstance(images, Exception):
        images_mock.side_effect = images
    job = {"start": MagicMock(return_value="job"), "complete": MagicMock(), "fail": MagicMock()}
    repaginate = MagicMock(side_effect=repaginate_error) if repaginate_error else MagicMock()
    with patch("app.db.session.get_sync_db", return_value=db), \
            patch("app.services.storage.storage_service", storage), \
            patch("app.pipeline.adapters.get_adapter", getter), \
            patch("app.pipeline.job_tracker.start_job", job["start"]), \
            patch("app.pipeline.job_tracker.complete_job", job["complete"]), \
            patch("app.pipeline.job_tracker.fail_job", job["fail"]), \
            patch("app.pipeline.tasks.process._build_page_map", return_value=[[10, 1]]), \
            patch("app.pipeline.tasks.process._recognize_document_images", images_mock), \
            patch("app.pipeline.tasks.process._repaginate_hwp_like", repaginate), \
            patch("app.pipeline.tasks.process._resolve_vision_credentials", return_value={"k": "v"}):
        try:
            result = eb.TextExtractBlock().run(_ctx(config))
        except Exception as exc:  # noqa: BLE001
            return exc, db, job, adapter, repaginate
    return result, db, job, adapter, repaginate


def test_text_extract_requires_document_id():
    with pytest.raises(ValueError):
        eb.TextExtractBlock().run(_ctx(document_id=None))


def test_text_extract_populates_document_fields():
    doc = _doc()
    result, db, job, adapter, _ = _extract(doc)
    assert result.output["text"] == "본문 텍스트입니다 안녕하세요"
    assert result.output["page_count"] == 1 and result.output["ocr_used"] is True
    assert result.metrics == {"chars": len(result.output["text"]), "tables": 1, "images": 1}
    assert doc.parsed_text == result.output["text"]
    assert doc.page_map == [[10, 1]]
    assert doc.ocr_page_confidence == [{"page_number": 1, "confidence": 0.8, "word_count": 5}]
    assert doc.tables[0]["detected_as"] == "ruled"
    assert doc.images == [{"page_number": 1, "storage_key": "img1"}]
    assert doc.language == "ko" and doc.page_count == 1
    assert doc.document_created_at == datetime(2026, 1, 1)
    assert doc.elements[0]["span_start"] == 0
    assert doc.elements[1]["span_start"] is None
    assert doc.elements[1]["metadata"]["image_path"] == "img1"
    assert doc.extraction_layout[0]["text"] == "x"
    job["complete"].assert_called_once()
    job["fail"].assert_not_called()
    db.close.assert_called_once()
    options = adapter.extract.call_args.args[1]
    assert options["k"] == "v" and options["detect_implicit_tables"] is True


def test_text_extract_empty_optional_fields_become_none():
    parsed = _parsed(metadata={})
    parsed.pages[0].table_candidates = []
    parsed.pages[0].ocr_confidence = None
    doc = _doc(document_created_at="keep")
    result, *_ = _extract(doc, parsed=parsed, images=[])
    assert doc.elements is None and doc.tables is None and doc.ocr_page_confidence is None
    assert doc.extraction_layout is None and doc.ocr_used is False
    assert doc.document_created_at == "keep"


def test_text_extract_image_recognition_failure_degrades():
    doc = _doc()
    result, *_ = _extract(doc, images=RuntimeError("vision down"))
    assert result.metrics["images"] == 0
    assert doc.images is None


def test_text_extract_skips_figures_when_disabled():
    doc = _doc()
    result, *_ = _extract(doc, config={"recognize_figures": False})
    assert result.metrics["images"] == 0


def test_text_extract_hwp_repaginate_is_best_effort():
    doc = _doc(filename="a.hwp")
    result, _, _, _, repaginate = _extract(doc, parsed=_parsed(format_id="hwp"), repaginate_error=RuntimeError("x"))
    repaginate.assert_called_once()
    assert result.output["chars"] > 0


def test_text_extract_unsupported_type_raises_permanent_and_fails_job():
    result, db, job, *_ = _extract(_doc(), adapter_error=UnsupportedFileTypeError(Path("a.xyz"), "x/y"))
    assert isinstance(result, BlockExecutionError)
    assert result.error_code == "FILE_UNSUPPORTED" and result.permanent
    db.rollback.assert_called_once()
    job["fail"].assert_called_once()
    db.close.assert_called_once()


def test_text_extract_wraps_generic_errors_as_extraction_failed():
    result, db, job, *_ = _extract(_doc(), extract_error=RuntimeError("boom"))
    assert isinstance(result, BlockExecutionError)
    assert result.error_code == "TEXT_EXTRACTION_FAILED" and not result.permanent
    db.rollback.assert_called_once()
    job["fail"].assert_called_once()


def test_text_extract_missing_document_is_wrapped():
    db = MagicMock()
    db.get.return_value = None
    with patch("app.db.session.get_sync_db", return_value=db), \
            patch("app.pipeline.job_tracker.start_job"), patch("app.pipeline.job_tracker.fail_job") as fail:
        with pytest.raises(BlockExecutionError) as exc:
            eb.TextExtractBlock().run(_ctx())
    assert exc.value.error_code == "TEXT_EXTRACTION_FAILED"
    fail.assert_called_once()


# ---- OcrBlock + 메타데이터 ----
def test_ocr_block_passes_upstream_through():
    assert eb.OcrBlock().run(_ctx(upstream={"text": "t"})).output == {"text": "t"}
    assert eb.OcrBlock().run(_ctx()).output == {}


@pytest.mark.parametrize("block,btype,schema", [
    (eb.FileValidateBlock, "file_validate", eb.FileValidateConfig),
    (eb.FormatDetectBlock, "format_detect", eb.FormatDetectConfig),
    (eb.TextExtractBlock, "text_extract", eb.TextExtractConfig),
    (eb.OcrBlock, "ocr", eb.OcrConfig),
])
def test_block_metadata(block, btype, schema):
    instance = block()
    assert (instance.block_type, instance.config_schema, instance.category) == (btype, schema, "입력·추출")


def test_text_extract_block_version():
    assert eb.TextExtractBlock().block_version == "1.16.0"


def test_config_defaults_and_validation():
    assert eb.TextExtractConfig().engine == "legacy"
    assert eb.FileValidateConfig().allowed_extensions == [".pdf", ".docx", ".hwp", ".hwpx"]
    with pytest.raises(Exception):
        eb.FileValidateConfig(max_pages="lots")
