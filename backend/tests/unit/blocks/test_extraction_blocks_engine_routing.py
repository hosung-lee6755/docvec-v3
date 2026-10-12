"""추출 엔진 3택(auto/docling/legacy) 해석 — 스캔 PDF 는 자동 모드에서만 전면 OCR 로 우회한다."""
from pathlib import Path
from unittest.mock import patch

from app.pipeline.blocks import extraction_blocks as eb

PDF = "application/pdf"


def _signals(has_text_layer, encrypted=False):
    return patch.object(eb, "_detect_pdf_signals", return_value=(has_text_layer, encrypted, 1.0))


def test_default_engine_is_auto():
    assert eb.TextExtractConfig().engine == "auto"


def test_auto_with_text_layer_uses_docling_silently():
    with _signals(True):
        assert eb.resolve_extract_engine("auto", Path("a.pdf"), PDF) == ("docling", None)


def test_auto_without_text_layer_uses_full_page_ocr_and_says_so():
    with _signals(False):
        engine, note = eb.resolve_extract_engine("auto", Path("a.pdf"), PDF)

    assert engine == "legacy"
    assert "텍스트 레이어" in note


def test_auto_with_encrypted_pdf_falls_back_to_docling_without_note():
    with _signals(False, encrypted=True):
        assert eb.resolve_extract_engine("auto", Path("a.pdf"), PDF) == ("docling", None)


def test_explicit_docling_is_obeyed_but_warns_on_scanned_pdf():
    with _signals(False):
        engine, note = eb.resolve_extract_engine("docling", Path("a.pdf"), PDF)

    assert engine == "docling"
    assert "스캔" in note and "자동" in note


def test_explicit_docling_with_text_layer_has_no_note():
    with _signals(True):
        assert eb.resolve_extract_engine("docling", Path("a.pdf"), PDF) == ("docling", None)


def test_legacy_is_never_probed():
    with patch.object(eb, "_detect_pdf_signals") as probe:
        assert eb.resolve_extract_engine("legacy", Path("a.pdf"), PDF) == ("legacy", None)
    probe.assert_not_called()


def test_non_pdf_always_uses_legacy_adapter_without_probe():
    with patch.object(eb, "_detect_pdf_signals") as probe:
        for engine in ("auto", "docling", "legacy"):
            assert eb.resolve_extract_engine(engine, Path("a.docx"), "") == ("legacy", None)
    probe.assert_not_called()
