"""app/services/access_policy.py 순수 규칙 테스트 — DB·Qdrant 없이 판정 의미론만 검증.

권한 규칙(계획서 m1-permission-model.plan.md "권한 규칙"):
  업로더 본인은 항상 열람. 그 외에는 (컬렉션 접근) AND (유효 등급 <= 열람등급) AND (ACL 비었거나 내 주체 포함).
"""
from app.services.access_policy import (
    UNRESTRICTED_ACL,
    AccessContext,
    DocumentAccessFacts,
    can_view,
    clearance_rank,
    document_access_payload,
    effective_level_rank,
    group_principal,
    user_principal,
)

U = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"
G = "33333333-3333-3333-3333-333333333333"
COL = "44444444-4444-4444-4444-444444444444"
COL2 = "55555555-5555-5555-5555-555555555555"


def _ctx(rank_level: str = "Internal", collections=(COL,), groups=()) -> AccessContext:
    return AccessContext.create(
        user_id=U, collection_ids=collections, clearance_level=rank_level, group_ids=groups
    )


def _facts(**over) -> DocumentAccessFacts:
    base = dict(
        document_id="d1", created_by=OTHER, collection_id=COL, security_level=None,
        collection_default_level=None, acl_principals=frozenset(),
    )
    base.update(over)
    return DocumentAccessFacts(**base)


def test_rank_order_and_defaults():
    assert clearance_rank("Public") < clearance_rank("Internal") < clearance_rank("Confidential")
    # 알 수 없는 열람등급은 가장 낮게(fail-closed)
    assert clearance_rank("bogus") == clearance_rank("Public")
    assert clearance_rank(None) == clearance_rank("Internal")


def test_effective_level_falls_back_doc_then_collection_then_public():
    assert effective_level_rank(_facts(security_level="Confidential")) == clearance_rank("Confidential")
    assert effective_level_rank(_facts(collection_default_level="Internal")) == clearance_rank("Internal")
    assert effective_level_rank(
        _facts(security_level="Public", collection_default_level="Confidential")
    ) == clearance_rank("Public")
    assert effective_level_rank(_facts()) == clearance_rank("Public")
    # 알 수 없는 문서 등급은 가장 높게(fail-closed)
    assert effective_level_rank(_facts(security_level="TopSecret")) == clearance_rank("Confidential")


def test_collection_access_required():
    assert can_view(_ctx(), _facts())
    assert not can_view(_ctx(collections=(COL2,)), _facts())
    assert not can_view(_ctx(), _facts(collection_id=None))


def test_level_must_not_exceed_clearance():
    assert can_view(_ctx("Internal"), _facts(security_level="Internal"))
    assert not can_view(_ctx("Internal"), _facts(security_level="Confidential"))
    assert not can_view(_ctx("Public"), _facts(collection_default_level="Internal"))
    assert can_view(_ctx("Confidential"), _facts(security_level="Confidential"))


def test_acl_restricts_to_listed_principals():
    restricted = _facts(acl_principals=frozenset({user_principal(OTHER)}))
    assert not can_view(_ctx(), restricted)
    assert can_view(_ctx(), _facts(acl_principals=frozenset({user_principal(U)})))
    by_group = _facts(acl_principals=frozenset({group_principal(G)}))
    assert not can_view(_ctx(), by_group)
    assert can_view(_ctx(groups=(G,)), by_group)


def test_acl_and_level_are_both_required():
    facts = _facts(security_level="Confidential", acl_principals=frozenset({user_principal(U)}))
    assert not can_view(_ctx("Internal"), facts)


def test_owner_always_sees_own_document():
    facts = _facts(
        created_by=U, collection_id=COL2, security_level="Confidential",
        acl_principals=frozenset({user_principal(OTHER)}),
    )
    assert can_view(_ctx("Public", collections=()), facts)


def test_payload_unrestricted_and_restricted():
    open_payload = document_access_payload(_facts(collection_default_level="Internal"))
    assert open_payload == {
        "sec_rank": clearance_rank("Internal"), "acl": [UNRESTRICTED_ACL], "owner_id": OTHER,
        "lifecycle": "active",
    }
    restricted = document_access_payload(_facts(acl_principals=frozenset({group_principal(G)})))
    # 업로더는 항상 목록에 포함되고, 목록은 정렬돼 결정적이다
    assert restricted["acl"] == sorted([group_principal(G), user_principal(OTHER)])


def test_context_principals_and_fingerprint():
    ctx = _ctx(groups=(G,))
    assert ctx.principals == frozenset({user_principal(U), group_principal(G)})
    assert ctx.acl_match_values == frozenset({UNRESTRICTED_ACL, user_principal(U), group_principal(G)})
    # 순서와 무관하게 같은 권한 조합이면 같은 지문, 하나라도 다르면 다른 지문
    a = AccessContext.create(U, (COL, COL2), "Internal", (G,))
    b = AccessContext.create(U, (COL2, COL), "Internal", (G,))
    assert a.fingerprint() == b.fingerprint()
    assert a.fingerprint() != AccessContext.create(U, (COL, COL2), "Confidential", (G,)).fingerprint()
    assert a.fingerprint() != AccessContext.create(U, (COL, COL2), "Internal", ()).fingerprint()
    assert a.fingerprint() != AccessContext.create(U, (COL,), "Internal", (G,)).fingerprint()
