"""v3 마일스톤 3 — 파일 서버 권한(DACL)을 문서 ACL로 바꾸는 규칙.

핵심 불변식: 결과는 원천보다 좁아질 수는 있어도 넓어지지는 않는다. 애매하면 보류한다.
"""
import struct

import pytest

from app.services.connectors.acl_mapping import (
    ACCESS_ALLOWED,
    ACCESS_DENIED,
    DECISION_HELD,
    DECISION_OPEN,
    DECISION_RESTRICTED,
    INHERIT_ONLY,
    Ace,
    SecurityDescriptorError,
    decide_acl,
    parse_security_descriptor,
)

DOM = "S-1-5-21-3128204629-1924712510-1209476672"
READ = 0x1200A9
FULL = 0x1F01FF
WRITE_ONLY = 0x2  # FILE_WRITE_DATA
SVC, ALICE, BOB, SALES, ADMIN = f"{DOM}-1103", f"{DOM}-1104", f"{DOM}-1105", f"{DOM}-1108", f"{DOM}-500"
USERS = {ALICE: "u-alice", BOB: "u-bob"}
GROUPS = {SALES: "g-sales"}


def _decide(aces):
    return decide_acl(aces, sid_to_user=USERS, sid_to_group=GROUPS, ignored_sids={SVC})


def allow(sid, mask=READ, flags=0):
    return Ace(ACCESS_ALLOWED, flags, mask, sid)


def deny(sid, mask=READ):
    return Ace(ACCESS_DENIED, 0, mask, sid)


@pytest.mark.parametrize(
    ("aces", "kind", "users", "groups", "reason"),
    [
        # 사용자 한 명, 그룹 하나에 열린 파일
        ([allow(ADMIN, FULL), allow(SVC), allow(ALICE)], DECISION_RESTRICTED, {"u-alice"}, set(), None),
        ([allow(ADMIN, FULL), allow(SVC), allow(SALES)], DECISION_RESTRICTED, set(), {"g-sales"}, None),
        # 넓은 권한 주체 → 컬렉션 권한만 적용
        ([allow(SVC), allow(f"{DOM}-513")], DECISION_OPEN, set(), set(), None),
        ([allow("S-1-1-0")], DECISION_OPEN, set(), set(), None),
        ([allow("S-1-5-11"), allow(ALICE)], DECISION_OPEN, set(), set(), None),
        # 읽기 거부 항목이 하나라도 있으면 보류(허용 목록으로 표현할 수 없다)
        ([deny(f"{DOM}-1109"), allow(SALES)], DECISION_HELD, set(), set(), "deny_ace"),
        ([deny(f"{DOM}-1109"), allow("S-1-1-0")], DECISION_HELD, set(), set(), "deny_ace"),
        # 쓰기만 거부하는 항목은 읽기 판정과 무관하다
        ([deny(BOB, WRITE_ONLY), allow(SALES)], DECISION_RESTRICTED, set(), {"g-sales"}, None),
        # 쓰기 권한만 있는 허용 항목은 읽기 주체가 아니다
        ([allow(BOB, WRITE_ONLY), allow(ALICE)], DECISION_RESTRICTED, {"u-alice"}, set(), None),
        # 아무도 매핑되지 않으면 보류(빈 목록은 "제한 없음"이라 열면 안 된다)
        ([allow(ADMIN, FULL), allow(SVC), allow("S-1-5-21-1-2-3-1001")], DECISION_HELD, set(), set(),
         "no_mapped_principal"),
        ([], DECISION_HELD, set(), set(), "no_mapped_principal"),
        # 일부만 매핑되면 매핑된 주체만 허용한다(원천보다 좁다)
        ([allow(ALICE), allow("S-1-5-21-1-2-3-1001")], DECISION_RESTRICTED, {"u-alice"}, set(), None),
        # 상속 전용 ACE는 파일 자체에 적용되지 않는다
        ([allow("S-1-1-0", flags=INHERIT_ONLY), allow(ALICE)], DECISION_RESTRICTED, {"u-alice"}, set(), None),
        # 알 수 없는 ACE 형식은 보류
        ([Ace(9, 0, READ, ALICE)], DECISION_HELD, set(), set(), "unsupported_ace"),
        # 수집용 계정은 매핑하지 않는다
        ([allow(SVC)], DECISION_HELD, set(), set(), "no_mapped_principal"),
    ],
)
def test_decide_acl(aces, kind, users, groups, reason):
    decision = _decide(aces)
    assert (decision.kind, set(decision.users), set(decision.groups), decision.reason) == (
        kind, users, groups, reason,
    )


def test_null_dacl_means_everyone():
    assert _decide(None).kind == DECISION_OPEN


def test_unmapped_sids_are_reported_for_operators():
    decision = _decide([allow(ALICE), allow("S-1-5-21-1-2-3-1001")])
    assert decision.unmapped == ("S-1-5-21-1-2-3-1001",)


# -- 보안 설명자 파서(MS-DTYP 자기 상대 형식) --------------------------------------

def _sid_bytes(sid: str) -> bytes:
    parts = sid.split("-")
    rev, auth, subs = int(parts[1]), int(parts[2]), [int(x) for x in parts[3:]]
    return bytes([rev, len(subs)]) + auth.to_bytes(6, "big") + struct.pack("<" + "I" * len(subs), *subs)


def _sd(aces, *, acl_revision=4, dacl_present=True):
    body = b""
    for t, flags, mask, sid in aces:
        sid_b = _sid_bytes(sid)
        body += struct.pack("<BBHI", t, flags, 8 + len(sid_b), mask) + sid_b
    acl = struct.pack("<BBHHH", acl_revision, 0, 8 + len(body), len(aces), 0) + body
    control = 0x8000 | (0x0004 if dacl_present else 0)
    header = struct.pack("<BBHIIII", 1, 0, control, 0, 0, 0, 20 if dacl_present else 0)
    return header + (acl if dacl_present else b"")


def test_parser_reads_revision_4_and_ds_revision_acls():
    for rev in (2, 3, 4):  # Samba는 3을 돌려준다(스파이크에서 확인)
        aces = parse_security_descriptor(_sd([(1, 0, READ, f"{DOM}-1109"), (0, 0, FULL, ADMIN)], acl_revision=rev))
        assert aces == [Ace(1, 0, READ, f"{DOM}-1109"), Ace(0, 0, FULL, ADMIN)]


def test_parser_returns_none_for_null_dacl():
    assert parse_security_descriptor(_sd([], dacl_present=False)) is None


@pytest.mark.parametrize("raw", [b"", b"\x01\x00", _sd([(0, 0, READ, ALICE)])[:-3], b"\x02" + b"\x00" * 19])
def test_parser_rejects_malformed_input(raw):
    with pytest.raises(SecurityDescriptorError):
        parse_security_descriptor(raw)
