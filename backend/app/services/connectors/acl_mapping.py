"""파일 서버 권한(NTFS DACL)을 문서 ACL로 바꾸는 순수 함수(v3 마일스톤 3).

불변식: 결과는 원천보다 좁아질 수는 있어도 넓어지지는 않는다. 애매하면 보류한다.

- v3 ACL은 허용 목록만 표현하고, 빈 목록은 "제한 없음"을 뜻한다. 그래서 읽기 거부(Deny) 항목이
  있거나 읽기 주체를 하나도 매핑하지 못하면 문서를 만들지 않고 보류한다.
- 넓은 권한 주체(Everyone, Authenticated Users, Domain Users, BUILTIN\\Users)에게 읽기가 열려 있으면
  ACL 없이 등록한다. 이때는 컬렉션 권한만 적용된다.
- 일부 SID만 매핑되면 매핑된 주체만 허용한다. 매핑되지 않은 SID는 운영자가 볼 수 있게 남긴다.

보안 설명자 파서는 MS-DTYP 2.4.6의 자기 상대(self-relative) 형식을 읽는다. smbprotocol의 파서는
Samba가 돌려주는 ACL revision 3을 거부해서 직접 둔다.
"""
from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass, field

ACCESS_ALLOWED = 0x00
ACCESS_DENIED = 0x01
INHERIT_ONLY = 0x08

# 읽기에 해당하는 접근 마스크 비트: FILE_READ_DATA, GENERIC_ALL, GENERIC_READ, MAXIMUM_ALLOWED
_READ_BITS = 0x00000001 | 0x10000000 | 0x80000000 | 0x02000000

_SE_DACL_PRESENT = 0x0004
_SE_SELF_RELATIVE = 0x8000
_HEADER = struct.Struct("<BBHIIII")
_ACL_HEADER = struct.Struct("<BBHHH")
_ACE_HEADER = struct.Struct("<BBHI")

DECISION_RESTRICTED = "restricted"
DECISION_OPEN = "open"
DECISION_HELD = "held"

HOLD_DENY_ACE = "deny_ace"
HOLD_NO_PRINCIPAL = "no_mapped_principal"
HOLD_UNSUPPORTED_ACE = "unsupported_ace"

_BROAD_SIDS = frozenset({"S-1-1-0", "S-1-5-11", "S-1-5-32-545"})
_DOMAIN_USERS_RID = "513"


class SecurityDescriptorError(ValueError):
    """보안 설명자를 해석할 수 없다. 호출자는 그 파일을 보류한다."""


@dataclass(frozen=True)
class Ace:
    type: int
    flags: int
    mask: int
    sid: str


@dataclass(frozen=True)
class AclDecision:
    kind: str
    users: frozenset[str] = field(default_factory=frozenset)
    groups: frozenset[str] = field(default_factory=frozenset)
    reason: str | None = None
    unmapped: tuple[str, ...] = ()


def descriptor_hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sid_at(raw: bytes, offset: int) -> str:
    if offset + 8 > len(raw):
        raise SecurityDescriptorError("SID out of range")
    revision, count = raw[offset], raw[offset + 1]
    end = offset + 8 + 4 * count
    if revision != 1 or end > len(raw):
        raise SecurityDescriptorError("bad SID")
    authority = int.from_bytes(raw[offset + 2:offset + 8], "big")
    subs = struct.unpack_from("<" + "I" * count, raw, offset + 8)
    return f"S-1-{authority}" + "".join(f"-{s}" for s in subs)


def parse_security_descriptor(raw: bytes) -> list[Ace] | None:
    """DACL의 ACE 목록을 돌려준다. DACL이 없으면(NULL DACL, 모두 허용) None."""
    if len(raw) < _HEADER.size:
        raise SecurityDescriptorError("too short")
    revision, _, control, _owner, _group, _sacl, dacl_offset = _HEADER.unpack_from(raw, 0)
    if revision != 1 or not control & _SE_SELF_RELATIVE:
        raise SecurityDescriptorError("not a self-relative descriptor")
    if not control & _SE_DACL_PRESENT or dacl_offset == 0:
        return None
    if dacl_offset + _ACL_HEADER.size > len(raw):
        raise SecurityDescriptorError("DACL out of range")
    acl_revision, _, acl_size, ace_count, _ = _ACL_HEADER.unpack_from(raw, dacl_offset)
    if acl_revision not in (2, 3, 4) or dacl_offset + acl_size > len(raw):
        raise SecurityDescriptorError("bad ACL header")

    aces, offset = [], dacl_offset + _ACL_HEADER.size
    for _ in range(ace_count):
        if offset + _ACE_HEADER.size > len(raw):
            raise SecurityDescriptorError("ACE out of range")
        ace_type, flags, size, mask = _ACE_HEADER.unpack_from(raw, offset)
        if size < _ACE_HEADER.size or offset + size > len(raw):
            raise SecurityDescriptorError("bad ACE size")
        sid = _sid_at(raw, offset + _ACE_HEADER.size) if ace_type in (ACCESS_ALLOWED, ACCESS_DENIED) else ""
        aces.append(Ace(ace_type, flags, mask, sid))
        offset += size
    return aces


def is_broad_sid(sid: str) -> bool:
    if sid in _BROAD_SIDS:
        return True
    return sid.startswith("S-1-5-21-") and sid.rsplit("-", 1)[-1] == _DOMAIN_USERS_RID


def _grants_read(ace: Ace) -> bool:
    return bool(ace.mask & _READ_BITS)


def decide_acl(
    aces: list[Ace] | None,
    *,
    sid_to_user: dict[str, str],
    sid_to_group: dict[str, str],
    ignored_sids: set[str] | frozenset[str] = frozenset(),
) -> AclDecision:
    if aces is None:
        return AclDecision(DECISION_OPEN)
    effective = [a for a in aces if not a.flags & INHERIT_ONLY]
    if any(a.type not in (ACCESS_ALLOWED, ACCESS_DENIED) for a in effective):
        return AclDecision(DECISION_HELD, reason=HOLD_UNSUPPORTED_ACE)
    if any(a.type == ACCESS_DENIED and _grants_read(a) for a in effective):
        return AclDecision(DECISION_HELD, reason=HOLD_DENY_ACE)

    readers = [a.sid for a in effective if a.type == ACCESS_ALLOWED and _grants_read(a)]
    readers = [s for s in dict.fromkeys(readers) if s not in ignored_sids]
    if any(is_broad_sid(s) for s in readers):
        return AclDecision(DECISION_OPEN)

    users = frozenset(sid_to_user[s] for s in readers if s in sid_to_user)
    groups = frozenset(sid_to_group[s] for s in readers if s in sid_to_group)
    unmapped = tuple(s for s in readers if s not in sid_to_user and s not in sid_to_group)
    if not users and not groups:
        return AclDecision(DECISION_HELD, reason=HOLD_NO_PRINCIPAL, unmapped=unmapped)
    return AclDecision(DECISION_RESTRICTED, users=users, groups=groups, unmapped=unmapped)
