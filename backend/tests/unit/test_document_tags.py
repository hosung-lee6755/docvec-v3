"""Coverage for the LLM-suggested tag accept/dismiss endpoints — a suggestion
promoted via accept-suggestion must behave exactly like a manually-added tag
(synced to Qdrant), while a dismissed suggestion must never touch Qdrant."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints.documents import accept_tag_suggestion, dismiss_tag_suggestion
from app.schemas.document import DocumentTagSuggestionRequest


def _doc(**kwargs):
    defaults = dict(
        id=uuid4(), created_by=None, collection_id=None,
        tags=None, suggested_tags=["예산", "계약서"],
    )
    defaults.update(kwargs)
    return MagicMock(**defaults)


@pytest.mark.asyncio
async def test_accept_suggestion_moves_tag_and_syncs_qdrant():
    user = MagicMock(id=uuid4())
    doc = _doc(created_by=user.id, tags=["기존태그"], suggested_tags=["예산", "계약서"])
    db = AsyncMock()
    db.scalar.return_value = doc

    with patch("app.services.qdrant_service.qdrant_service") as mock_qdrant:
        result = await accept_tag_suggestion(
            doc.id, DocumentTagSuggestionRequest(tag="예산"), db=db, current_user=user
        )

    assert doc.tags == ["기존태그", "예산"]
    assert doc.suggested_tags == ["계약서"]
    db.commit.assert_awaited_once()
    mock_qdrant.set_payload_by_document.assert_called_once()
    assert result == {"tags": doc.tags, "suggested_tags": doc.suggested_tags}


@pytest.mark.asyncio
async def test_accept_suggestion_dedupes_against_existing_tags():
    user = MagicMock(id=uuid4())
    doc = _doc(created_by=user.id, tags=["예산"], suggested_tags=["예산"])
    db = AsyncMock()
    db.scalar.return_value = doc

    with patch("app.services.qdrant_service.qdrant_service"):
        await accept_tag_suggestion(
            doc.id, DocumentTagSuggestionRequest(tag="예산"), db=db, current_user=user
        )

    assert doc.tags == ["예산"]
    assert doc.suggested_tags is None


@pytest.mark.asyncio
async def test_accept_suggestion_clears_suggested_tags_to_none_when_emptied():
    user = MagicMock(id=uuid4())
    doc = _doc(created_by=user.id, tags=[], suggested_tags=["예산"])
    db = AsyncMock()
    db.scalar.return_value = doc

    with patch("app.services.qdrant_service.qdrant_service"):
        await accept_tag_suggestion(
            doc.id, DocumentTagSuggestionRequest(tag="예산"), db=db, current_user=user
        )

    assert doc.suggested_tags is None


@pytest.mark.asyncio
async def test_accept_suggestion_404_when_missing():
    db = AsyncMock()
    db.scalar.return_value = None
    user = MagicMock(id=uuid4())

    with pytest.raises(HTTPException) as exc_info:
        await accept_tag_suggestion(
            uuid4(), DocumentTagSuggestionRequest(tag="예산"), db=db, current_user=user
        )

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_accept_suggestion_rejects_user_without_access():
    owner_id = uuid4()
    other_user = MagicMock(id=uuid4())
    doc = _doc(created_by=owner_id, collection_id=None, tags=[], suggested_tags=["예산"])
    db = AsyncMock()
    db.scalar.return_value = doc

    with pytest.raises(HTTPException) as exc_info:
        await accept_tag_suggestion(
            doc.id, DocumentTagSuggestionRequest(tag="예산"), db=db, current_user=other_user
        )

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_dismiss_suggestion_removes_without_touching_tags_or_qdrant():
    user = MagicMock(id=uuid4())
    doc = _doc(created_by=user.id, tags=["기존태그"], suggested_tags=["예산", "계약서"])
    db = AsyncMock()
    db.scalar.return_value = doc

    with patch("app.services.qdrant_service.qdrant_service") as mock_qdrant:
        result = await dismiss_tag_suggestion(
            doc.id, DocumentTagSuggestionRequest(tag="예산"), db=db, current_user=user
        )

    assert doc.tags == ["기존태그"]  # untouched
    assert doc.suggested_tags == ["계약서"]
    mock_qdrant.set_payload_by_document.assert_not_called()
    assert result == {"suggested_tags": doc.suggested_tags}


@pytest.mark.asyncio
async def test_dismiss_suggestion_404_when_missing():
    db = AsyncMock()
    db.scalar.return_value = None
    user = MagicMock(id=uuid4())

    with pytest.raises(HTTPException) as exc_info:
        await dismiss_tag_suggestion(
            uuid4(), DocumentTagSuggestionRequest(tag="예산"), db=db, current_user=user
        )

    assert exc_info.value.status_code == 404
