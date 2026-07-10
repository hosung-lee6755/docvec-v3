"""Authorization/IDOR regression coverage for app.api.v1.permissions — the
security review flagged this module's role-based access model as sound, but
it had zero automated tests, so a future refactor could silently reintroduce
an IDOR without anything catching it."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.v1.permissions import (
    check_collection_access,
    check_document_access,
    check_project_access,
)


def _user(user_id):
    return MagicMock(id=user_id)


@pytest.mark.asyncio
async def test_check_project_access_grants_owner_without_membership_lookup():
    owner_id = uuid4()
    project = MagicMock(created_by=str(owner_id))
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=project)

    result = await check_project_access(db, uuid4(), _user(owner_id), min_role="editor")

    assert result is project
    db.scalar.assert_awaited_once()  # only the Project lookup — no membership query needed


@pytest.mark.asyncio
async def test_check_project_access_grants_member_with_sufficient_role():
    project = MagicMock(created_by=str(uuid4()))
    membership = MagicMock(role="editor")
    db = AsyncMock()
    db.scalar = AsyncMock(side_effect=[project, membership])

    result = await check_project_access(db, uuid4(), _user(uuid4()), min_role="viewer")

    assert result is project


@pytest.mark.asyncio
async def test_check_project_access_denies_member_with_insufficient_role():
    project = MagicMock(created_by=str(uuid4()))
    membership = MagicMock(role="viewer")
    db = AsyncMock()
    db.scalar = AsyncMock(side_effect=[project, membership])

    with pytest.raises(HTTPException) as exc_info:
        await check_project_access(db, uuid4(), _user(uuid4()), min_role="editor")

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_check_project_access_denies_non_member():
    project = MagicMock(created_by=str(uuid4()))
    db = AsyncMock()
    db.scalar = AsyncMock(side_effect=[project, None])

    with pytest.raises(HTTPException) as exc_info:
        await check_project_access(db, uuid4(), _user(uuid4()), min_role="viewer")

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_check_project_access_404s_when_project_missing():
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=None)

    with pytest.raises(HTTPException) as exc_info:
        await check_project_access(db, uuid4(), _user(uuid4()), min_role="viewer")

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_check_collection_access_grants_owner():
    owner_id = uuid4()
    collection = MagicMock(created_by=str(owner_id), project_id=None)
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=collection)

    result = await check_collection_access(db, uuid4(), _user(owner_id), min_role="editor")

    assert result is collection


@pytest.mark.asyncio
async def test_check_collection_access_denies_stranger_on_personal_collection():
    """A collection with no project_id is only reachable via direct
    CollectionMember rows — a user who is neither the owner nor an explicit
    member must be denied (the core IDOR case: guessing another user's
    collection_id must not grant access)."""
    collection = MagicMock(created_by=str(uuid4()), project_id=None)
    db = AsyncMock()
    db.scalar = AsyncMock(side_effect=[collection, None])

    with pytest.raises(HTTPException) as exc_info:
        await check_collection_access(db, uuid4(), _user(uuid4()), min_role="viewer")

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_check_collection_access_restrict_to_members_excludes_plain_project_members():
    """restrict_to_members=True must opt a collection OUT of the usual
    project-membership auto-inheritance — a project member with no explicit
    CollectionMember row must still be denied."""
    collection = MagicMock(created_by=str(uuid4()), project_id=str(uuid4()), restrict_to_members=True)
    db = AsyncMock()
    # Only two db.scalar calls expected: the collection lookup, then straight
    # to the CollectionMember lookup (project-inheritance branch is skipped
    # entirely because restrict_to_members is True).
    db.scalar = AsyncMock(side_effect=[collection, None])

    with pytest.raises(HTTPException) as exc_info:
        await check_collection_access(db, uuid4(), _user(uuid4()), min_role="viewer")

    assert exc_info.value.status_code == 403
    assert db.scalar.await_count == 2


@pytest.mark.asyncio
async def test_check_document_access_denies_stranger_with_no_collection():
    """A document with no collection_id can only be accessed by its creator —
    this is the direct IDOR case for a personal, unfiled document."""
    doc = MagicMock(created_by=str(uuid4()), collection_id=None)
    db = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await check_document_access(db, doc, _user(uuid4()), min_role="viewer")

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_check_document_access_grants_creator():
    creator_id = uuid4()
    doc = MagicMock(created_by=str(creator_id), collection_id=None)
    db = AsyncMock()

    await check_document_access(db, doc, _user(creator_id), min_role="viewer")  # must not raise
