"""Docling 변환기는 프로세스마다 한 번만 만든다.

문서마다 새로 만들면 레이아웃·표·OCR 모델을 매번 다시 올린다. 8쪽 문서에서 첫 변환 18초,
재사용 11초로 실측했다(2026-11-13). extract 워커는 프로세스가 하나라 한 벌만 남는다.
"""
from unittest.mock import MagicMock, patch

import pytest

from app.pipeline.adapters import docling_adapter


@pytest.fixture
def fake_docling():
    modules = {
        "docling": MagicMock(),
        "docling.datamodel": MagicMock(),
        "docling.datamodel.base_models": MagicMock(),
        "docling.datamodel.pipeline_options": MagicMock(),
        "docling.document_converter": MagicMock(),
    }
    docling_adapter._converter = None
    with patch.dict("sys.modules", modules):
        yield modules["docling.document_converter"]
    docling_adapter._converter = None


def test_converter_is_built_once_per_process(fake_docling):
    first = docling_adapter._get_converter()
    second = docling_adapter._get_converter()

    assert first is second
    fake_docling.DocumentConverter.assert_called_once()


def test_converter_keeps_korean_ocr_and_picture_images(fake_docling):
    import sys

    options_module = sys.modules["docling.datamodel.pipeline_options"]
    docling_adapter._get_converter()

    options = options_module.PdfPipelineOptions.return_value
    assert options.do_ocr is True
    assert options.generate_picture_images is True
    options_module.EasyOcrOptions.assert_called_once_with(lang=["ko"])
