"""v3 마일스톤 2 — 문서 본문이 밖으로 나가는 조회(원문 미리보기, 다운로드 URL 발급,
컬렉션 내보내기)가 감사 로그에 남는지 검증한다. 목록·상세 같은 일반 조회는 대상이 아니다."""
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.api.v1.endpoints import collections as collections_api
from app.api.v1.endpoints.documents import metadata as metadata_api
from app.db.models.audit_log import AuditLog
from tests.unit.api_pg_helpers import (  # noqa: F401
    add_member,
    db_session,
    make_collection,
    make_document,
    make_project,
    make_user,
)

pytestmark = pytest.mark.asyncio


async def _audit(db, action: str) -> list[AuditLog]:
    return list((await db.scalars(select(AuditLog).where(AuditLog.action == action))).all())


@pytest.fixture
async def world(db_session):  # noqa: F811
    db = db_session
    owner = await make_user(db, "editor")
    reader = await make_user(db, "viewer")
    project = await make_project(db, owner)
    await add_member(db, project, reader, "viewer", owner)
    col = await make_collection(db, owner, project)
    pdf = await make_document(db, owner, col, original_filename="a.pdf", filename="a.pdf")
    txt = await make_document(db, owner, col, original_filename="b.txt")
    await db.commit()
    return dict(db=db, reader=reader, col=col, pdf=pdf, txt=txt)


async def test_preview_is_audited(world):
    with patch("app.services.document_service.get_download_url", return_value="https://x/a.pdf"):
        await metadata_api.get_document_preview(world["pdf"].id, world["db"], world["reader"])

    [row] = await _audit(world["db"], "document.preview")
    assert (str(row.user_id), row.resource_type, row.resource_id) == (
        str(world["reader"].id), "document", str(world["pdf"].id)
    )


async def test_unsupported_preview_is_not_audited(world):
    from fastapi import HTTPException

    with patch("app.services.preview_service.preview_url_for", return_value=(None, None, None)):
        with pytest.raises(HTTPException) as exc:
            await metadata_api.get_document_preview(world["txt"].id, world["db"], world["reader"])
    assert exc.value.status_code == 422
    assert await _audit(world["db"], "document.preview") == []


async def test_download_url_is_audited(world):
    with patch("app.services.document_service.get_download_url", return_value="https://x/a.pdf"):
        await metadata_api.get_document_download_url(world["pdf"].id, world["db"], world["reader"])

    [row] = await _audit(world["db"], "document.download")
    assert (str(row.user_id), row.resource_id) == (str(world["reader"].id), str(world["pdf"].id))


async def test_collection_export_is_audited_with_document_count(world):
    with patch("app.services.qdrant_service.qdrant_service.scroll_by_document", return_value=[]):
        await collections_api.export_collection(world["col"].id, world["db"], world["reader"])

    [row] = await _audit(world["db"], "collection.export")
    assert row.resource_id == str(world["col"].id)
    assert row.detail == {"document_count": 2}
