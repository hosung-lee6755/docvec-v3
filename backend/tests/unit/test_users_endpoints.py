"""Regression coverage for delete_user's ownership cascade (users.py).

Deleting an account that owns projects/collections used to fail every time
with an IntegrityError, because no FK into users.id has ON DELETE CASCADE at
the DB level — 3 real accounts (qa-admin@example.com, test@docver.kr,
wftest2@example.com) could not be deleted, 2026-07-29. delete_user now reuses
cascade_delete_project/cascade_delete_collection before deleting the user row,
and turns any remaining IntegrityError into an explicit 409 instead of a bare
500. These tests exercise the cascade call ordering and the 409 fallback with
a mocked session rather than a live Postgres FK graph.
"""
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.api.v1.endpoints.users import SYSTEM_USER_ID, delete_user


def _user(role="admin"):
    return MagicMock(id=uuid4(), role=role)


def _scalars_result(items):
    result = MagicMock()
    result.all.return_value = items
    return result


def _db_with_target(target):
    lookup_result = MagicMock()
    lookup_result.scalar_one_or_none.return_value = target
    db = AsyncMock()
    db.execute = AsyncMock(return_value=lookup_result)
    return db


@pytest.mark.asyncio
async def test_delete_user_rejects_non_admin():
    db = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await delete_user(uuid4(), db=db, current_user=_user(role="editor"))

    assert exc_info.value.status_code == 403
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_delete_user_rejects_system_user():
    db = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await delete_user(SYSTEM_USER_ID, db=db, current_user=_user())

    assert exc_info.value.status_code == 403
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_delete_user_404_when_not_found():
    db = _db_with_target(None)

    with pytest.raises(HTTPException) as exc_info:
        await delete_user(uuid4(), db=db, current_user=_user())

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_user_cascades_owned_projects_and_collections():
    target_id = uuid4()
    target = MagicMock(id=target_id)
    db = _db_with_target(target)

    owned_project = MagicMock()
    owned_collection = MagicMock()
    db.scalars = AsyncMock(side_effect=[
        _scalars_result([owned_project]),
        _scalars_result([owned_collection]),
    ])

    with patch(
        "app.api.v1.endpoints.projects.cascade_delete_project", AsyncMock()
    ) as mock_cascade_project, patch(
        "app.api.v1.endpoints.collections.cascade_delete_collection", AsyncMock()
    ) as mock_cascade_collection:
        await delete_user(target_id, db=db, current_user=_user())

    # Owned resources must be torn down before the user row itself, or the
    # remaining FKs from those resources into users.id block the delete.
    mock_cascade_project.assert_awaited_once_with(db, owned_project)
    mock_cascade_collection.assert_awaited_once_with(db, owned_collection)
    db.delete.assert_awaited_once_with(target)
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_user_returns_409_when_commit_still_fails():
    """A not-null reference the cascade doesn't cover (e.g. a dictionary entry
    with only an owner, no project/collection) must surface as a clear 409,
    not an unexplained 500."""
    target_id = uuid4()
    target = MagicMock(id=target_id)
    db = _db_with_target(target)
    db.scalars = AsyncMock(side_effect=[
        _scalars_result([]),
        _scalars_result([]),
    ])
    db.commit = AsyncMock(side_effect=IntegrityError("stmt", {}, Exception("fk violation")))

    with patch(
        "app.api.v1.endpoints.projects.cascade_delete_project", AsyncMock()
    ), patch(
        "app.api.v1.endpoints.collections.cascade_delete_collection", AsyncMock()
    ):
        with pytest.raises(HTTPException) as exc_info:
            await delete_user(target_id, db=db, current_user=_user())

    assert exc_info.value.status_code == 409
    db.rollback.assert_awaited_once()
