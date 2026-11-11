"""v3 권한 누출 매트릭스 — 모든 응답 경로가 같은 가시성 규칙을 따르는지 한 번에 검증.

사용자(열람등급·그룹·멤버십) × 문서(보안등급·ACL·컬렉션 기본 등급) 조합마다 기대 결과를
손으로 적어 두고(can_view로 계산하지 않는다 — 규칙 구현과 기대값이 같은 코드에서 나오면
버그가 양쪽에 같이 숨는다), 실제 Postgres + Qdrant(로컬 메모리 모드)로 각 경로를 호출한다.

"stale" 문서는 Postgres에서 Confidential로 올렸지만 Qdrant 사본은 Public으로 남은 상황
(동기화 실패)을 흉내 낸다 — 검색 경로의 Postgres 재확인이 막아야 한다.

"smb_*" 문서는 파일 서버 커넥터가 가져온 문서다(v3 마일스톤 3). 업로더가 사람 대신 커넥터 전용
시스템 계정이므로, "업로더는 다 본다" 규칙으로 사람이 원천의 제한을 우회하지 못해야 한다.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from app.api.v1.endpoints import golden_queries as golden_api
from app.api.v1.endpoints import stats as stats_api
from app.api.v1.endpoints.documents import listing as listing_api
from app.api.v1.permissions import check_document_access
from app.core.config import settings
from app.db.models.document_acl import DocumentAclEntry
from app.db.models.golden_query import GoldenQuery
from app.db.models.user_group import UserGroup, UserGroupMember
from app.pipeline.tasks import chat as chat_task
from app.schemas.document import DocumentSummarySearchRequest
from app.schemas.golden_query import GoldenEvalRunRequest
from app.schemas.search import SearchRequest
from app.services import search_service
from app.services.access_payload import point_access_payload
from app.services.access_policy import build_access_context, load_document_facts
from app.services.qdrant_service import qdrant_service
from app.services.summary_index import SUMMARY_COLLECTION_NAME
from tests.unit.api_pg_helpers import (  # noqa: F401
    add_member,
    db_session,
    make_collection,
    make_document,
    make_project,
    make_user,
)

pytestmark = pytest.mark.asyncio

DIM = 4
VECTOR = [1.0, 0.0, 0.0, 0.0]
ALL_DOCS = {"pub", "int", "conf", "acl_user", "acl_group", "col_default", "stale", "smb_open", "smb_group"}

# 손으로 쓴 기대값. 업로더(owner)는 전부 본다.
EXPECTED = {
    "owner": ALL_DOCS - {"smb_group"},                 # 커넥터 문서의 업로더가 아니다
    "public_reader": {"pub", "smb_open"},
    "internal_reader": {"pub", "int", "acl_user", "smb_open"},     # acl_user는 이 사용자를 지정
    "confidential_reader": {"pub", "int", "conf", "col_default", "stale", "smb_open"},
    "group_member": {"pub", "int", "acl_group", "smb_open", "smb_group"},       # Internal + 그룹 A
    "outsider": set(),                                 # Confidential이지만 프로젝트 비회원
}


async def _user(db, clearance: str, project=None, owner=None):
    user = await make_user(db, "viewer")
    user.clearance_level = clearance
    await db.flush()
    if project is not None:
        await add_member(db, project, user, "viewer", owner)
    return user


@pytest.fixture
async def world(db_session):  # noqa: F811
    db = db_session
    owner = await make_user(db, "editor")
    project = await make_project(db, owner)
    users = {
        "owner": owner,
        "public_reader": await _user(db, "Public", project, owner),
        "internal_reader": await _user(db, "Internal", project, owner),
        "confidential_reader": await _user(db, "Confidential", project, owner),
        "group_member": await _user(db, "Internal", project, owner),
        "outsider": await _user(db, "Confidential"),
    }
    group = UserGroup(id=str(uuid4()), name=f"A-{uuid4().hex[:6]}")
    db.add(group)
    await db.flush()
    db.add(UserGroupMember(group_id=str(group.id), user_id=str(users["group_member"].id)))

    # 커넥터 전용 시스템 계정(registry.new_service_user와 같은 모양)
    connector_user = await make_user(db, "viewer")
    connector_user.auth_source, connector_user.is_active = "system", False

    col = await make_collection(db, owner, project, "c")
    conf_col = await make_collection(db, owner, project, "d", default_security_level="Confidential")
    docs = {
        "pub": await make_document(db, owner, col, security_level="Public", tags=["pub"]),
        "int": await make_document(db, owner, col, security_level="Internal", tags=["int"]),
        "conf": await make_document(db, owner, col, security_level="Confidential", tags=["conf"]),
        "acl_user": await make_document(db, owner, col, tags=["acl_user"]),
        "acl_group": await make_document(db, owner, col, tags=["acl_group"]),
        "col_default": await make_document(db, owner, conf_col, tags=["col_default"]),
        "stale": await make_document(db, owner, col, security_level="Confidential", tags=["stale"]),
        "smb_open": await make_document(db, connector_user, col, security_level="Public", tags=["smb_open"]),
        "smb_group": await make_document(db, connector_user, col, security_level="Internal", tags=["smb_group"]),
    }
    db.add(DocumentAclEntry(
        document_id=str(docs["acl_user"].id), principal_type="user",
        principal_id=str(users["internal_reader"].id),
    ))
    db.add(DocumentAclEntry(
        document_id=str(docs["acl_group"].id), principal_type="group", principal_id=str(group.id),
    ))
    db.add(DocumentAclEntry(
        document_id=str(docs["smb_group"].id), principal_type="group", principal_id=str(group.id),
    ))
    await db.flush()

    names = {str(d.id): key for key, d in docs.items()}
    facts = await load_document_facts(db, list(names))
    mem = QdrantClient(":memory:")
    for collection in (settings.qdrant_collection_name, SUMMARY_COLLECTION_NAME):
        mem.create_collection(collection, vectors_config=VectorParams(size=DIM, distance=Distance.COSINE))
        points = []
        for i, (doc_id, key) in enumerate(names.items()):
            doc_facts = facts[doc_id]
            if key == "stale":  # 사본이 동기화되지 않아 Public으로 남은 상태
                doc_facts = SimpleNamespace(**{**doc_facts.__dict__, "security_level": "Public"})
            payload = {
                "document_id": doc_id, "text": key, "filename": key, "summary": key,
                **point_access_payload(doc_facts),
            }
            points.append(PointStruct(id=i, vector=VECTOR, payload=payload))
        mem.upsert(collection, points=points)

    provider = MagicMock()
    provider.embed.return_value = [VECTOR]
    with (
        patch.object(qdrant_service, "_client", mem),
        patch("app.services.embedding.get_embedding_provider", return_value=provider),
        patch("app.services.summary_index.get_embedding_provider", return_value=provider),
        patch.object(search_service, "_embed_query", return_value=VECTOR),
        patch.object(search_service, "expand_query", side_effect=lambda q: (q, [])),
        patch.object(search_service, "record_hits"),
        patch("app.services.chunk_stats.record_hits"),
        patch("app.services.reranker.cross_encoder_rerank", side_effect=lambda q, c, **kw: c),
        patch.object(golden_api, "_embed_query", return_value=VECTOR),
        patch("app.core.rate_limit.enforce_user_rate_limit"),
    ):
        yield SimpleNamespace(db=db, users=users, docs=docs, names=names, col=col, conf_col=conf_col)


def _keys(world, doc_ids) -> set[str]:
    return {world.names[str(d)] for d in doc_ids if str(d) in world.names}


def _per_user():
    return pytest.mark.parametrize("who", sorted(EXPECTED))


@_per_user()
async def test_check_document_access(world, who):
    """상세·청크·원본·다운로드·메타데이터 엔드포인트가 공유하는 단건 판정."""
    visible = set()
    for key, doc in world.docs.items():
        try:
            await check_document_access(world.db, doc, world.users[who])
            visible.add(key)
        except HTTPException as exc:
            assert exc.status_code == 403
    assert visible == EXPECTED[who]


@_per_user()
async def test_search_api(world, who):
    response = await search_service.perform_search(
        world.db, world.users[who], SearchRequest(query="q", limit=50)
    )
    items = response.items if hasattr(response, "items") else response
    assert _keys(world, [i.document_id for i in items]) == EXPECTED[who]


@_per_user()
async def test_chat_chunk_retrieval(world, who):
    uid = str(world.users[who].id)
    chunks = await world.db.run_sync(
        lambda s: chat_task._retrieve_chunks(s, uid, "q", None, None, limit=50)
    )
    assert _keys(world, [c["document_id"] for c in chunks]) == EXPECTED[who]


@_per_user()
async def test_chat_document_retrieval(world, who):
    """표·요약 기반 채팅 경로(문서 행 조회)."""
    uid = str(world.users[who].id)
    docs = await world.db.run_sync(lambda s: chat_task._accessible_documents(s, uid, None, None))
    assert _keys(world, [d.id for d in docs]) == EXPECTED[who]


@_per_user()
async def test_summary_search(world, who):
    result = await listing_api.search_documents_by_summary(
        DocumentSummarySearchRequest(query="q", limit=50), world.db, world.users[who]
    )
    assert _keys(world, [i["document_id"] for i in result["items"]]) == EXPECTED[who]


@_per_user()
async def test_document_list_tags_and_stats(world, who):
    user = world.users[who]
    listed = await listing_api.list_documents(
        db=world.db, current_user=user, page=1, limit=100, collection_id=None, project_id=None,
        status=None, filename=None, sort_by="created_at", order="desc",
    )
    ids = [i["id"] if isinstance(i, dict) else i.id for i in listed["items"]]
    assert _keys(world, ids) == EXPECTED[who]

    tags = await listing_api.list_all_tags(world.db, user)
    tag_items = tags["tags"]
    assert set(tag_items) & ALL_DOCS == EXPECTED[who]

    stats = await stats_api.get_stats(world.db, user)
    assert stats["total_documents"] == len(EXPECTED[who])


@_per_user()
async def test_golden_eval_only_retrieves_visible_documents(world, who):
    db, user = world.db, world.users[who]
    db.add(GoldenQuery(
        collection_id=str(world.col.id), query="q",
        expected_document_ids=[str(d.id) for d in world.docs.values()],
        created_by=str(world.users["owner"].id),
    ))
    await db.flush()
    try:
        run = await golden_api.run_golden_eval(world.col.id, GoldenEvalRunRequest(top_k=50), db, user)
    except HTTPException as exc:
        assert exc.status_code == 403 and not EXPECTED[who]
        return
    retrieved = _keys(world, run.results[0]["retrieved_document_ids"])
    in_collection = EXPECTED[who] - {"col_default"}  # 평가는 컬렉션 c 범위
    assert retrieved == in_collection


async def test_answer_cache_is_partitioned_by_access(world):
    """채팅 답변 캐시 키에 들어가는 권한 지문 — 보이는 문서 집합이 다르면 지문도 달라야 한다."""
    fingerprints = {}
    for who, user in world.users.items():
        fingerprints[who] = (await build_access_context(world.db, user)).fingerprint()
    for a in EXPECTED:
        for b in EXPECTED:
            if EXPECTED[a] != EXPECTED[b]:
                assert fingerprints[a] != fingerprints[b], (a, b)
    key_a = chat_task._answer_cache_key("q", None, None, "m", fingerprints["public_reader"])
    key_b = chat_task._answer_cache_key("q", None, None, "m", fingerprints["confidential_reader"])
    assert key_a != key_b
