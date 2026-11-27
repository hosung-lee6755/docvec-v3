"""문서 유형 결정 순서(2026-11-27): 문서 지정값 → 컬렉션 기본값 → 판별값 → 일반 문서."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services import document_type as dt


def test_normalize_accepts_auto_and_known_types():
    assert dt.normalize_document_type(None) is None
    assert dt.normalize_document_type(" AUTO ") is None
    assert dt.normalize_document_type("Regulation") == "regulation"
    with pytest.raises(ValueError):
        dt.normalize_document_type("contract")


def test_effective_type_prefers_document_then_collection_then_detected():
    assert dt.effective_document_type("general", "regulation", "regulation") == "general"
    assert dt.effective_document_type(None, "regulation", "general") == "regulation"
    assert dt.effective_document_type(None, None, "regulation") == "regulation"
    assert dt.effective_document_type(None, None, None) == "general"


def test_collection_default_type_reads_collection_or_none():
    db = MagicMock()
    db.query.return_value.filter.return_value.scalar.return_value = "regulation"
    assert dt.collection_default_type(db, SimpleNamespace(collection_id="c1")) == "regulation"
    assert dt.collection_default_type(db, SimpleNamespace(collection_id=None)) is None
