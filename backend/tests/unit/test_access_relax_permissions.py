"""v3 마일스톤 2 — 등급을 낮추거나 ACL 제한을 푸는 일은 문서 업로더와 컬렉션 소유자만 할 수 있다.

등급을 올리거나 제한을 더하는 일(더 좁히는 방향)은 지금처럼 문서 editor도 할 수 있다.
마일스톤 1의 알려진 제약 16번을 닫는 결정이다.
"""
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints import collections as collections_api
from app.api.v1.endpoints.documents import acl as acl_api
from app.api.v1.endpoints.documents import metadata as metadata_api
from app.schemas.access import AclEntryIn, DocumentAclUpdate
from app.schemas.document import DocumentMetadataUpdateRequest
from app.services.access_policy import is_relaxing_acl, is_relaxing_level
from tests.unit.api_pg_helpers import (  # noqa: F401
    add_member,
    db_session,
    make_collection,
    make_document,
    make_project,
    make_user,
)

pytestmark = pytest.mark.asyncio

SYNC = "app.api.v1.access_sync.sync_document_access"


async def _expect(awaitable, status: int) -> None:
    with pytest.raises(HTTPException) as exc:
        await awaitable
    assert exc.value.status_code == status


def _acl(*user_ids) -> DocumentAclUpdate:
    return DocumentAclUpdate(entries=[AclEntryIn(principal_type="user", principal_id=u) for u in user_ids])


def _level(level) -> DocumentMetadataUpdateRequest:
    return DocumentMetadataUpdateRequest(security_level=level)


@pytest.fixture
async def world(db_session):  # noqa: F811
    db = db_session
    col_owner = await make_user(db, "editor")
    uploader = await make_user(db, "editor")
    editor = await make_user(db, "editor")
    other = await make_user(db, "viewer")
    project = await make_project(db, col_owner)
    for user in (uploader, editor):
        await add_member(db, project, user, "editor", col_owner)
    await add_member(db, project, other, "viewer", col_owner)
    col = await make_collection(db, col_owner, project)
    doc = await make_document(db, uploader, col, security_level="Internal")
    await db.commit()
    with patch(SYNC, new=AsyncMock(return_value=[])):
        yield dict(db=db, col_owner=col_owner, uploader=uploader, editor=editor,
                   other=other, col=col, doc=doc)


def test_relaxing_rules():
    assert is_relaxing_level("Confidential", "Internal") is True
    assert is_relaxing_level("Internal", None) is True  # 비우면 Public(기본값)
    assert is_relaxing_level("Internal", "Confidential") is False
    assert is_relaxing_level(None, "Public") is False
    assert is_relaxing_acl(set(), {"u:a"}) is False  # 제한을 새로 거는 것
    assert is_relaxing_acl({"u:a", "u:b"}, {"u:a"}) is False  # 허용 대상을 줄이는 것
    assert is_relaxing_acl({"u:a"}, set()) is True  # 제한 해제
    assert is_relaxing_acl({"u:a"}, {"u:a", "u:b"}) is True  # 허용 대상을 늘리는 것


async def test_editor_can_raise_but_not_lower_document_level(world):
    db, doc, editor = world["db"], world["doc"], world["editor"]
    raised = await metadata_api.update_document_metadata(doc.id, _level("Confidential"), db, editor)
    assert raised.security_level == "Confidential"

    await _expect(metadata_api.update_document_metadata(doc.id, _level("Public"), db, editor), 403)
    # 등급을 지우면(None) 컬렉션 기본값이나 Public으로 떨어지므로 이것도 하향이다
    await _expect(metadata_api.update_document_metadata(doc.id, _level(None), db, editor), 403)


@pytest.mark.parametrize("who", ["uploader", "col_owner"])
async def test_uploader_and_collection_owner_can_lower_document_level(world, who):
    db, doc = world["db"], world["doc"]
    lowered = await metadata_api.update_document_metadata(doc.id, _level("Public"), db, world[who])
    assert lowered.security_level == "Public"


async def test_editor_can_narrow_but_not_relax_acl(world):
    db, doc, editor, uploader, other = (
        world["db"], world["doc"], world["editor"], world["uploader"], world["other"]
    )
    await acl_api.replace_document_acl(doc.id, _acl(editor.id, other.id), db, editor)
    narrowed = await acl_api.replace_document_acl(doc.id, _acl(editor.id), db, editor)
    assert [str(e.principal_id) for e in narrowed.entries] == [str(editor.id)]

    await _expect(acl_api.replace_document_acl(doc.id, _acl(editor.id, other.id), db, editor), 403)
    await _expect(acl_api.replace_document_acl(doc.id, _acl(), db, editor), 403)

    cleared = await acl_api.replace_document_acl(doc.id, _acl(), db, uploader)
    assert cleared.restricted is False


async def test_acl_response_tells_whether_caller_can_relax(world):
    db, doc = world["db"], world["doc"]
    assert (await acl_api.get_document_acl(doc.id, db, world["uploader"])).can_relax is True
    assert (await acl_api.get_document_acl(doc.id, db, world["col_owner"])).can_relax is True
    assert (await acl_api.get_document_acl(doc.id, db, world["editor"])).can_relax is False


async def test_only_collection_owner_can_lower_collection_default_level(world):
    db, col = world["db"], world["col"]
    up = collections_api.CollectionUpdate(default_security_level="Confidential")
    down = collections_api.CollectionUpdate(default_security_level="Internal")

    await collections_api.update_collection(col.id, up, db, world["editor"])
    await _expect(collections_api.update_collection(col.id, down, db, world["editor"]), 403)
    clear = collections_api.CollectionUpdate(default_security_level=None)
    await _expect(collections_api.update_collection(col.id, clear, db, world["uploader"]), 403)

    lowered = await collections_api.update_collection(col.id, down, db, world["col_owner"])
    assert lowered.default_security_level == "Internal"
