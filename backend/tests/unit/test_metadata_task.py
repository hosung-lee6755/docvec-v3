"""Coverage for app.pipeline.tasks.metadata.extract_metadata — the LLM-based
keyword/entity extraction task that populates Document.suggested_tags for the
user to accept/dismiss in the tag UI. Mirrors the structure of the analogous
(untested) generate_summary task: sync SQLAlchemy session via get_sync_db,
local Qwen provider via get_llm_provider."""

from unittest.mock import MagicMock, patch

from app.pipeline.tasks.metadata import _parse_keywords, extract_metadata


def _document(parsed_text="문서 내용", tags=None):
    doc = MagicMock()
    doc.parsed_text = parsed_text
    doc.tags = tags
    doc.suggested_tags = None
    doc.metadata_status = "PENDING"
    return doc


def _run(doc, generated_text):
    db = MagicMock()
    db.get.return_value = doc
    provider = MagicMock()
    provider.generate.return_value = generated_text

    with patch("app.db.session.get_sync_db", return_value=db), \
         patch("app.services.llm.get_llm_provider", return_value=provider):
        return extract_metadata("doc-1")


def test_extract_metadata_parses_one_keyword_per_line():
    doc = _document()
    result = _run(doc, "예산\n계약서\n입찰")

    assert result["status"] == "DONE"
    assert doc.suggested_tags == ["예산", "계약서", "입찰"]
    assert doc.metadata_status == "DONE"


def test_extract_metadata_strips_numbering_and_bullets():
    doc = _document()
    _run(doc, "1. 예산\n- 계약서\n* 입찰")

    assert doc.suggested_tags == ["예산", "계약서", "입찰"]


def test_extract_metadata_excludes_tags_already_on_document():
    doc = _document(tags=["예산"])
    _run(doc, "예산\n계약서")

    assert doc.suggested_tags == ["계약서"]


def test_extract_metadata_dedupes_case_insensitively():
    doc = _document()
    _run(doc, "AI\nai\nAI")

    assert doc.suggested_tags == ["AI"]


def test_extract_metadata_caps_at_ten_tags():
    doc = _document()
    lines = "\n".join(f"키워드{i}" for i in range(15))
    _run(doc, lines)

    assert len(doc.suggested_tags) == 10


def test_extract_metadata_drops_han_heavy_lines():
    doc = _document()
    _run(doc, "예산\n中文关键词完全没有韩文")

    assert doc.suggested_tags == ["예산"]


def test_extract_metadata_fails_on_empty_text():
    doc = _document(parsed_text="   ")
    result = _run(doc, "예산")

    assert result["status"] == "FAILED"
    assert doc.metadata_status == "FAILED"
    assert doc.suggested_tags is None


def test_extract_metadata_returns_not_found_when_document_missing():
    db = MagicMock()
    db.get.return_value = None

    with patch("app.db.session.get_sync_db", return_value=db):
        result = extract_metadata("missing-doc")

    assert result["status"] == "NOT_FOUND"


def test_extract_metadata_sets_failed_on_provider_error():
    doc = _document()
    db = MagicMock()
    db.get.return_value = doc
    provider = MagicMock()
    provider.generate.side_effect = RuntimeError("model unavailable")

    with patch("app.db.session.get_sync_db", return_value=db), \
         patch("app.services.llm.get_llm_provider", return_value=provider):
        result = extract_metadata("doc-1")

    assert result["status"] == "FAILED"
    assert doc.metadata_status == "FAILED"


def test_parse_keywords_drops_overlong_lines():
    long_line = "가" * 200
    assert _parse_keywords(f"예산\n{long_line}", exclude=set()) == ["예산"]
