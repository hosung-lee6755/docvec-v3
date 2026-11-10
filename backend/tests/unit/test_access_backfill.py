"""권한 사본 백필(scripts/backfill_access_payload.py의 본체) — 실제 Postgres + Qdrant 호출 모킹."""
from unittest.mock import MagicMock, patch

import pytest

from app.core.config import settings
from app.services.access_payload import backfill_access_payloads
from tests.unit.api_pg_helpers import db_session, make_collection, make_document, make_user  # noqa: F401

pytestmark = pytest.mark.asyncio

QDRANT = "app.services.qdrant_service.qdrant_service"


async def _world(db):
    owner = await make_user(db, "editor")
    col = await make_collection(db, owner, default_security_level="Internal")
    a = await make_document(db, owner, col)
    b = await make_document(db, owner, col, security_level="Confidential")
    return owner, col, a, b


async def test_dry_run_counts_without_touching_qdrant(db_session):  # noqa: F811
    await _world(db_session)
    with patch(QDRANT) as qdrant:
        qdrant.collection_exists.return_value = False
        stats = await db_session.run_sync(lambda s: backfill_access_payloads(s, dry_run=True))

    assert stats["documents"] >= 2 and stats["synced"] == 0
    qdrant.ensure_access_indexes.assert_not_called()
    qdrant.set_payload_by_document.assert_not_called()


async def test_backfill_pushes_postgres_permissions_to_both_collections(db_session):  # noqa: F811
    owner, col, a, b = await _world(db_session)
    with patch(QDRANT) as qdrant:
        qdrant.collection_exists.return_value = True
        stats = await db_session.run_sync(lambda s: backfill_access_payloads(s, batch_size=1))

    assert stats["failed"] == [] and stats["synced"] == stats["documents"]
    assert len(stats["collections"]) == 2
    assert qdrant.ensure_access_indexes.call_count == 2
    pushed = {
        (call.args[0], call.args[1]): call.args[2]
        for call in qdrant.set_payload_by_document.call_args_list
    }
    main = settings.qdrant_collection_name
    assert pushed[(main, str(a.id))] == {
        "sec_rank": 1, "acl": ["*"], "owner_id": str(owner.id), "collection_id": str(col.id),
    }  # 문서 등급 없음 → 컬렉션 기본(Internal)
    assert pushed[(main, str(b.id))]["sec_rank"] == 2


async def test_backfill_reports_failures_and_continues(db_session):  # noqa: F811
    _, _, a, b = await _world(db_session)

    def fail_for_a(collection, document_id, payload):
        if document_id == str(a.id):
            raise RuntimeError("qdrant down")

    with patch(QDRANT) as qdrant:
        qdrant.collection_exists.return_value = False
        qdrant.set_payload_by_document = MagicMock(side_effect=fail_for_a)
        stats = await db_session.run_sync(lambda s: backfill_access_payloads(s))

    assert stats["failed"] == [str(a.id)]
    assert stats["synced"] == stats["documents"] - 1
