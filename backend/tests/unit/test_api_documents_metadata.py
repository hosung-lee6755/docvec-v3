"""documents/metadata.py 엔드포인트(태그/메타데이터/이미지/미리보기/다운로드/오류) — 실제 Postgres(db_session)."""
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.api.v1.endpoints.documents import metadata as md
from app.core.config import settings
from app.schemas.document import (
    DocumentMetadataUpdateRequest,
    DocumentTagsUpdateRequest,
    DocumentTagSuggestionRequest,
)
from tests.unit._docs_api_support import add_doc, assert_http_error, owner_user, stranger_user
from tests.unit._docs_api_support import db_session  # noqa: F401


@pytest.fixture
def qdrant(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr("app.services.qdrant_service.qdrant_service", fake)
    return fake


# -------------------------------------------------------------------- tags
async def test_update_tags_strips_dedupes_keeps_order_and_syncs_index(db_session, qdrant):  # noqa: F811
    doc = await add_doc(db_session, "m-tags")

    result = await md.update_document_tags(
        doc.id, DocumentTagsUpdateRequest(tags=[" 법무 ", "계약", "법무", "   ", "계약"]), db_session, owner_user()
    )

    assert result == {"tags": ["법무", "계약"]}
    await db_session.refresh(doc)
    assert doc.tags == ["법무", "계약"]
    qdrant.set_payload_by_document.assert_called_once_with(
        settings.qdrant_collection_name, str(doc.id), {"tags": ["법무", "계약"]}
    )


async def test_update_tags_with_only_blank_values_clears_tags_to_null(db_session, qdrant):  # noqa: F811
    doc = await add_doc(db_session, "m-tags-clear", tags=["old"])

    result = await md.update_document_tags(doc.id, DocumentTagsUpdateRequest(tags=["  "]), db_session, owner_user())

    assert result == {"tags": []}
    await db_session.refresh(doc)
    assert doc.tags is None


async def test_update_tags_404_and_403(db_session, qdrant):  # noqa: F811
    doc = await add_doc(db_session, "m-tags-g")
    body = DocumentTagsUpdateRequest(tags=["a"])

    await assert_http_error(md.update_document_tags(uuid4(), body, db_session, owner_user()), 404)
    await assert_http_error(md.update_document_tags(doc.id, body, db_session, stranger_user()), 403)
    qdrant.set_payload_by_document.assert_not_called()


async def test_accept_suggestion_appends_once_and_keeps_suggestion_visible(db_session, qdrant):  # noqa: F811
    doc = await add_doc(db_session, "m-accept", tags=["기존"], suggested_tags=["신규", "다른"])
    body = DocumentTagSuggestionRequest(tag="신규")

    first = await md.accept_tag_suggestion(doc.id, body, db_session, owner_user())
    second = await md.accept_tag_suggestion(doc.id, body, db_session, owner_user())

    assert first == second == {"tags": ["기존", "신규"], "suggested_tags": ["신규", "다른"]}
    assert qdrant.set_payload_by_document.call_count == 2


async def test_accept_suggestion_starts_tag_list_from_scratch(db_session, qdrant):  # noqa: F811
    doc = await add_doc(db_session, "m-accept-new")

    result = await md.accept_tag_suggestion(doc.id, DocumentTagSuggestionRequest(tag="처음"), db_session, owner_user())

    assert result["tags"] == ["처음"]


async def test_accept_and_dismiss_suggestion_404_and_403(db_session, qdrant):  # noqa: F811
    doc = await add_doc(db_session, "m-sugg-g")
    body = DocumentTagSuggestionRequest(tag="t")

    for endpoint in (md.accept_tag_suggestion, md.dismiss_tag_suggestion):
        await assert_http_error(endpoint(uuid4(), body, db_session, owner_user()), 404)
        await assert_http_error(endpoint(doc.id, body, db_session, stranger_user()), 403)


async def test_dismiss_suggestion_removes_only_that_tag_and_never_touches_qdrant(db_session, qdrant):  # noqa: F811
    doc = await add_doc(db_session, "m-dismiss", suggested_tags=["a", "b"])

    first = await md.dismiss_tag_suggestion(doc.id, DocumentTagSuggestionRequest(tag="a"), db_session, owner_user())
    last = await md.dismiss_tag_suggestion(doc.id, DocumentTagSuggestionRequest(tag="b"), db_session, owner_user())

    assert first == {"suggested_tags": ["b"]}
    assert last == {"suggested_tags": None}  # 비면 NULL로 저장
    qdrant.set_payload_by_document.assert_not_called()


# ---------------------------------------------------------------- metadata
async def test_update_metadata_applies_only_fields_present_in_request(db_session):  # noqa: F811
    doc = await add_doc(db_session, "m-meta", author="홍길동", organization="기존 조직")
    body = DocumentMetadataUpdateRequest(security_level="Confidential", organization=None)

    result = await md.update_document_metadata(doc.id, body, db_session, owner_user())

    assert result.security_level == "Confidential"
    assert result.organization is None  # 명시적 None은 값을 지운다
    assert result.author == "홍길동"  # 요청에 없던 필드는 그대로


def test_metadata_request_rejects_unknown_security_level():
    with pytest.raises(ValidationError):
        DocumentMetadataUpdateRequest(security_level="TopSecret")


async def test_update_metadata_marks_title_language_category_as_user_edited(db_session):  # noqa: F811
    doc = await add_doc(db_session, "m-meta-edit")
    body = DocumentMetadataUpdateRequest(title="  새 제목 ", language="en", category="제안서")

    result = await md.update_document_metadata(doc.id, body, db_session, owner_user())

    assert (result.title, result.language, result.category) == ("새 제목", "en", "제안서")
    assert sorted(result.user_edited_fields) == ["category", "language", "title"]


async def test_update_metadata_reset_fields_clears_value_and_mark(db_session):  # noqa: F811
    doc = await add_doc(db_session, "m-meta-reset", title="수정본", user_edited_fields=["title", "category"])

    result = await md.update_document_metadata(
        doc.id, DocumentMetadataUpdateRequest(reset_fields=["title"]), db_session, owner_user()
    )

    assert result.title is None
    assert result.user_edited_fields == ["category"]


async def test_update_metadata_syncs_language_to_chunks(db_session):  # noqa: F811
    from sqlalchemy import select

    from app.db.models.document_chunk import DocumentChunk

    from tests.unit._docs_api_support import doc_with_run

    doc, run = await doc_with_run(db_session, "m-meta-lang")
    db_session.add(DocumentChunk(document_id=doc.id, run_id=run.id, chunk_order=0, chunk_text="x", language="ko"))
    await db_session.flush()

    await md.update_document_metadata(
        doc.id, DocumentMetadataUpdateRequest(language="en"), db_session, owner_user()
    )

    langs = (await db_session.scalars(select(DocumentChunk.language).where(DocumentChunk.document_id == doc.id))).all()
    assert langs == ["en"]


def test_metadata_request_validates_language_and_reset_fields():
    with pytest.raises(ValidationError):
        DocumentMetadataUpdateRequest(language="xx")
    with pytest.raises(ValidationError):
        DocumentMetadataUpdateRequest(reset_fields=["author"])


async def test_update_metadata_404_and_403(db_session):  # noqa: F811
    doc = await add_doc(db_session, "m-meta-g")
    body = DocumentMetadataUpdateRequest(author="x")

    await assert_http_error(md.update_document_metadata(uuid4(), body, db_session, owner_user()), 404)
    await assert_http_error(md.update_document_metadata(doc.id, body, db_session, stranger_user()), 403)
    assert doc.author != "x"


# ------------------------------------------------------------------ images
async def test_images_builds_presigned_urls_and_counts_detected_pictures(db_session):  # noqa: F811
    doc = await add_doc(
        db_session, "m-img",
        images=[{"page_number": 1, "storage_key": "k1", "text": "그림1"}, {"page_number": 2, "storage_key": "k2"}],
        elements=[{"type": "picture"}, {"type": "picture"}, {"type": "paragraph"}],
    )
    storage = MagicMock()
    storage.get_presigned_url.side_effect = lambda bucket, key: f"https://s/{bucket}/{key}"

    with patch("app.services.storage.storage_service", storage):
        result = await md.get_document_images(doc.id, db_session, owner_user())

    bucket = settings.minio_bucket_artifacts
    assert result["images"] == [
        {"page_number": 1, "text": "그림1", "url": f"https://s/{bucket}/k1"},
        {"page_number": 2, "text": "", "url": f"https://s/{bucket}/k2"},
    ]
    assert result["detected_count"] == 2


async def test_images_detected_count_is_none_for_legacy_documents_and_guards(db_session):  # noqa: F811
    doc = await add_doc(db_session, "m-img-legacy")

    with patch("app.services.storage.storage_service", MagicMock()):
        result = await md.get_document_images(doc.id, db_session, owner_user())
        await assert_http_error(md.get_document_images(uuid4(), db_session, owner_user()), 404)
        await assert_http_error(md.get_document_images(doc.id, db_session, stranger_user()), 403)

    assert result["images"] == [] and result["detected_count"] is None


# ----------------------------------------------------------------- preview
async def test_preview_pdf_returns_presigned_original_without_conversion(db_session):  # noqa: F811
    doc = await add_doc(db_session, "m-prev-pdf", original_filename="Report.PDF")

    with (
        patch("app.services.document_service.get_download_url", return_value="https://dl/x") as dl,
        patch("app.services.preview_service.preview_url_for") as convert,
    ):
        result = await md.get_document_preview(doc.id, db_session, owner_user())

    assert result == {"url": "https://dl/x", "kind": "pdf", "approximate": False}
    dl.assert_called_once_with(doc.minio_key)
    convert.assert_not_called()


async def test_preview_converts_non_pdf_and_reports_unsupported_as_422(db_session):  # noqa: F811
    doc = await add_doc(db_session, "m-prev-docx", original_filename="a.docx")

    with patch("app.services.preview_service.preview_url_for", return_value=("https://p/y", "html", True)) as convert:
        result = await md.get_document_preview(doc.id, db_session, owner_user())
    assert result == {"url": "https://p/y", "kind": "html", "approximate": True}
    convert.assert_called_once_with(str(doc.id), "a.docx", doc.minio_key)

    with patch("app.services.preview_service.preview_url_for", return_value=(None, None, False)):
        await assert_http_error(md.get_document_preview(doc.id, db_session, owner_user()), 422)


async def test_preview_404_and_403(db_session):  # noqa: F811
    doc = await add_doc(db_session, "m-prev-g")
    await assert_http_error(md.get_document_preview(uuid4(), db_session, owner_user()), 404)
    await assert_http_error(md.get_document_preview(doc.id, db_session, stranger_user()), 403)


# -------------------------------------------------------------- pages-text
async def test_pages_text_splits_pdf_text_by_page_map(db_session):  # noqa: F811
    doc = await add_doc(db_session, "m-pages", original_filename="a.pdf", parsed_text="AAABBBCC", page_map=[[3, 1], [6, 2], [8, 3]])

    result = await md.get_document_pages_text(doc.id, db_session, owner_user())

    assert result["pages"] == [
        {"page_number": 1, "text": "AAA"}, {"page_number": 2, "text": "BBB"}, {"page_number": 3, "text": "CC"},
    ]


async def test_pages_text_without_page_map_is_single_page_or_empty(db_session):  # noqa: F811
    with_text = await add_doc(db_session, "m-pages-one", original_filename="a.pdf", parsed_text="전체")
    empty = await add_doc(db_session, "m-pages-empty", original_filename="b.pdf")

    assert (await md.get_document_pages_text(with_text.id, db_session, owner_user()))["pages"] == [{"page_number": 1, "text": "전체"}]
    assert (await md.get_document_pages_text(empty.id, db_session, owner_user()))["pages"] == []


async def test_pages_text_non_pdf_uses_preview_pdf_pages_then_falls_back(db_session):  # noqa: F811
    doc = await add_doc(db_session, "m-pages-docx", original_filename="a.docx", parsed_text="본문")
    preview_pages = [{"page_number": 1, "text": "미리보기 PDF 1쪽"}]

    with patch("app.services.preview_service.pdf_pages_text_for", return_value=preview_pages):
        assert (await md.get_document_pages_text(doc.id, db_session, owner_user()))["pages"] == preview_pages
    with patch("app.services.preview_service.pdf_pages_text_for", return_value=[]):
        assert (await md.get_document_pages_text(doc.id, db_session, owner_user()))["pages"] == [{"page_number": 1, "text": "본문"}]


async def test_pages_text_404_and_403(db_session):  # noqa: F811
    doc = await add_doc(db_session, "m-pages-g", original_filename="a.pdf")
    await assert_http_error(md.get_document_pages_text(uuid4(), db_session, owner_user()), 404)
    await assert_http_error(md.get_document_pages_text(doc.id, db_session, stranger_user()), 403)


# ----------------------------------------------------------- download/error
async def test_download_returns_presigned_url_and_enforces_access(db_session):  # noqa: F811
    doc = await add_doc(db_session, "m-dl")

    with patch("app.services.document_service.get_download_url", return_value="https://dl/z") as dl:
        assert await md.get_document_download_url(doc.id, db_session, owner_user()) == {"url": "https://dl/z"}
        await assert_http_error(md.get_document_download_url(doc.id, db_session, stranger_user()), 403)
        await assert_http_error(md.get_document_download_url(uuid4(), db_session, owner_user()), 404)

    dl.assert_called_once_with(doc.minio_key)


async def test_error_endpoint_returns_failure_details_only_for_failed_documents(db_session):  # noqa: F811
    failed = await add_doc(db_session, "m-err-f", status="FAILED", error_message="파싱 실패")
    healthy = await add_doc(db_session, "m-err-ok", status="INDEXED")

    result = await md.get_document_error(failed.id, db_session, owner_user())

    assert (result["status"], result["error_message"], str(result["document_id"])) == ("FAILED", "파싱 실패", str(failed.id))
    assert result["failed_at"] is not None
    await assert_http_error(md.get_document_error(healthy.id, db_session, owner_user()), 400)
    await assert_http_error(md.get_document_error(uuid4(), db_session, owner_user()), 404)
    await assert_http_error(md.get_document_error(failed.id, db_session, stranger_user()), 403)
