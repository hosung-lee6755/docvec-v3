"""qdrant_access_filter를 실제 Qdrant 필터 엔진(로컬 메모리 모드)에 걸어 검증.

페이로드는 access_payload.point_access_payload로 만든 것과 같은 모양을 쓴다.
"""
import pytest
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from app.services.access_payload import point_access_payload
from app.services.access_policy import AccessContext, DocumentAccessFacts, group_principal, user_principal

U, OTHER, G = "u-1", "u-2", "g-1"
COL, COL2 = "c-1", "c-2"
DIM = 4


def _facts(doc_id, **over):
    base = dict(
        document_id=doc_id, created_by=OTHER, collection_id=COL, security_level=None,
        collection_default_level=None, acl_principals=frozenset(),
    )
    base.update(over)
    return DocumentAccessFacts(**base)


DOCS = {
    "public": _facts("public"),
    "internal": _facts("internal", security_level="Internal"),
    "confidential": _facts("confidential", security_level="Confidential"),
    "col_default_conf": _facts("col_default_conf", collection_default_level="Confidential"),
    "acl_other": _facts("acl_other", acl_principals=frozenset({user_principal("u-3")})),
    "acl_group": _facts("acl_group", acl_principals=frozenset({group_principal(G)})),
    "acl_me": _facts("acl_me", acl_principals=frozenset({user_principal(U)})),
    "other_col": _facts("other_col", collection_id=COL2),
    "mine_conf_acl": _facts(
        "mine_conf_acl", created_by=U, security_level="Confidential",
        acl_principals=frozenset({user_principal("u-3")}),
    ),
}


MINE_ELSEWHERE = _facts("mine_elsewhere", created_by=U, collection_id="c-3", security_level="Confidential")
ALL_DOCS = {**DOCS, "mine_elsewhere": MINE_ELSEWHERE}


@pytest.fixture(scope="module")
def client():
    c = QdrantClient(":memory:")
    c.create_collection("t", vectors_config=VectorParams(size=DIM, distance=Distance.COSINE))
    points = []
    for i, (doc_id, facts) in enumerate(DOCS.items()):
        payload = {"document_id": doc_id, **point_access_payload(facts)}
        points.append(PointStruct(id=i, vector=[1.0, 0.1 * i, 0.0, 0.0], payload=payload))
    # 백필 전(권한 필드 없음) 포인트와 검색 제외 포인트
    points.append(PointStruct(id=100, vector=[1, 0, 0, 0], payload={"document_id": "legacy", "collection_id": COL}))
    disabled = {"document_id": "disabled", **point_access_payload(_facts("disabled")), "disabled": True}
    points.append(PointStruct(id=101, vector=[1, 0, 0, 0], payload=disabled))
    # 내가 올렸지만 지금은 접근 권한이 없는 컬렉션에 있는 문서 — 범위 검색엔 안 나오고
    # 가시성 필터(목록·요약 검색)엔 나와야 한다.
    elsewhere = {"document_id": "mine_elsewhere", **point_access_payload(MINE_ELSEWHERE)}
    points.append(PointStruct(id=102, vector=[1, 0, 0, 0], payload=elsewhere))
    c.upsert("t", points=points)
    return c


def _visible(client, ctx, scope=None):
    from app.services.access_policy import qdrant_access_filter

    res = client.query_points("t", query=[1, 0, 0, 0], limit=50, query_filter=qdrant_access_filter(ctx, scope))
    return {p.payload["document_id"] for p in res.points}


def test_internal_clearance_without_groups(client):
    ctx = AccessContext.create(U, [COL], "Internal")
    assert _visible(client, ctx) == {"public", "internal", "acl_me", "mine_conf_acl"}


def test_group_membership_and_confidential(client):
    ctx = AccessContext.create(U, [COL, COL2], "Confidential", [G])
    assert _visible(client, ctx) == {
        "public", "internal", "confidential", "col_default_conf", "acl_group", "acl_me",
        "other_col", "mine_conf_acl",
    }


def test_public_clearance(client):
    ctx = AccessContext.create(U, [COL], "Public")
    assert _visible(client, ctx) == {"public", "acl_me", "mine_conf_acl"}


def test_scope_narrows_even_for_owner(client):
    ctx = AccessContext.create(U, [COL, COL2], "Confidential", [G])
    assert _visible(client, ctx, scope=[COL2]) == {"other_col"}


def test_unbackfilled_and_disabled_points_never_match(client):
    ctx = AccessContext.create(U, [COL], "Confidential", [G])
    visible = _visible(client, ctx)
    assert "legacy" not in visible and "disabled" not in visible


def test_filter_agrees_with_can_view(client):
    from app.services.access_policy import can_view

    for clearance in ("Public", "Internal", "Confidential"):
        for groups in ((), (G,)):
            ctx = AccessContext.create(U, [COL, COL2], clearance, groups)
            expected = {d for d, f in DOCS.items() if can_view(ctx, f)}
            assert _visible(client, ctx) == expected, (clearance, groups)


def _visible_unscoped(client, ctx):
    from app.services.access_policy import qdrant_visibility_filter

    res = client.query_points("t", query=[1, 0, 0, 0], limit=50, query_filter=qdrant_visibility_filter(ctx))
    return {p.payload["document_id"] for p in res.points}


def test_visibility_filter_agrees_with_can_view(client):
    """요약 검색용 필터는 범위 없이 can_view(=목록 SQL 조건)와 정확히 같아야 한다."""
    from app.services.access_policy import can_view

    for collections in ([], [COL], [COL, COL2]):
        for clearance in ("Public", "Internal", "Confidential"):
            for groups in ((), (G,)):
                ctx = AccessContext.create(U, collections, clearance, groups)
                expected = {d for d, f in ALL_DOCS.items() if can_view(ctx, f)}
                assert _visible_unscoped(client, ctx) == expected, (collections, clearance, groups)


def test_visibility_filter_without_collections_shows_only_own(client):
    ctx = AccessContext.create(U, [], "Confidential", [G])
    assert _visible_unscoped(client, ctx) == {"mine_conf_acl", "mine_elsewhere"}
