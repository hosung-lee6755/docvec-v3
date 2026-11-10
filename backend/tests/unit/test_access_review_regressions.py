"""코드·보안 리뷰에서 나온 v3 권한 누출 경로의 회귀 테스트.

누출 매트릭스(test_access_leak_matrix.py)의 world 픽스처와 손으로 쓴 기대표를 그대로 쓴다.
- 컬렉션 내보내기가 등급·ACL을 무시하고 본문 전체를 돌려주던 문제
- 컬렉션 목록의 문서 수가 숨겨진 문서까지 세던 문제
- 채팅 답변 캐시가 문서 권한 변경 뒤에도 낡은 답변·인용을 돌려주던 문제
- 삭제된 사용자의 열람등급이 기본값(Internal)으로 잡히던 문제
"""
import json
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints import collections as collections_api
from app.pipeline.tasks import chat as chat_task
from app.services.access_policy import build_access_context, build_access_context_sync
from tests.unit.test_access_leak_matrix import EXPECTED, _keys, _per_user, world  # noqa: F401
from tests.unit.api_pg_helpers import db_session  # noqa: F401

pytestmark = pytest.mark.asyncio


@_per_user()
async def test_collection_export_only_contains_visible_documents(world, who):  # noqa: F811
    try:
        response = await collections_api.export_collection(world.col.id, world.db, world.users[who])
    except HTTPException as exc:
        assert exc.status_code == 403 and not EXPECTED[who]
        return
    exported = json.loads(response.body)["documents"]
    assert _keys(world, [d["id"] for d in exported]) == EXPECTED[who] - {"col_default"}
    for doc in exported:  # 본문도 그 문서 것만
        assert all(c["text"] == world.names[doc["id"]] for c in doc["chunks"])


@_per_user()
async def test_collection_list_counts_only_visible_documents(world, who):  # noqa: F811
    result = await collections_api.list_collections(None, world.db, world.users[who])
    mine = {str(world.col.id), str(world.conf_col.id)}
    total = sum(i["document_count"] for i in result["items"] if str(i["id"]) in mine)
    assert total == len(EXPECTED[who])


async def test_cached_answer_is_dropped_when_a_cited_document_becomes_hidden(world):  # noqa: F811
    db, reader = world.db, world.users["internal_reader"]
    ctx = await build_access_context(db, reader)
    payload = {"answer": "a", "citations": [
        {"document_id": str(world.docs["pub"].id)}, {"document_id": str(world.docs["int"].id)},
    ]}
    check = lambda: db.run_sync(  # noqa: E731
        lambda s: chat_task._cited_documents_still_visible(s, ctx, payload)
    )
    assert await check() is True

    # 캐시 이후 인용 문서 하나가 Confidential로 올라갔다 → 캐시를 쓰면 안 된다
    world.docs["int"].security_level = "Confidential"
    await db.flush()
    assert await check() is False


async def test_cached_answer_without_citations_is_reusable(world):  # noqa: F811
    ctx = await build_access_context(world.db, world.users["public_reader"])
    ok = await world.db.run_sync(
        lambda s: chat_task._cited_documents_still_visible(s, ctx, {"answer": "a", "citations": []})
    )
    assert ok is True


async def test_missing_user_gets_lowest_clearance(world):  # noqa: F811
    ctx = await world.db.run_sync(lambda s: build_access_context_sync(s, str(uuid4())))
    assert ctx.clearance_rank == 0 and not ctx.collection_ids
