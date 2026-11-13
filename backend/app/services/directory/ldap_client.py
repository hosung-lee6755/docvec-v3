"""사내 Active Directory(LDAP) 접근 어댑터(v3 마일스톤 3).

ldap3를 직접 다루는 코드는 이 모듈에만 둔다. 계정 생성·그룹 동기화 같은 규칙은
`provisioning.py`가 이 모듈의 결과(불변 dataclass)만 받아 처리한다.

보안 원칙:
- 사용자 입력은 LDAP 필터에 넣기 전에 반드시 이스케이프한다.
- 빈 비밀번호로 bind하지 않는다. AD는 빈 비밀번호 simple bind를 익명 bind로 성공시킨다.
- 평문 LDAP는 쓰지 않는다. LDAPS나 StartTLS를 요구하고, 개발용으로만 예외를 둔다.
- AD에 연결하지 못하면 DirectoryUnavailable을 던진다. 호출자는 이때 로그인을 거부한다.
"""
from __future__ import annotations

import ssl
from dataclasses import dataclass
from typing import Protocol

import ldap3
from ldap3.core.exceptions import (
    LDAPBindError,
    LDAPException,
    LDAPPasswordIsMandatoryError,
    LDAPStartTLSError,
)
from ldap3.protocol.formatters.formatters import format_sid
from ldap3.utils.conv import escape_filter_chars

# userAccountControl 비트: ACCOUNTDISABLE
_UAC_DISABLED = 0x2
_PAGE_SIZE = 500
# 중첩 그룹을 한 번에 펼치는 AD 전용 매칭 규칙(LDAP_MATCHING_RULE_IN_CHAIN)
_IN_CHAIN = "1.2.840.113556.1.4.1941"
_MAX_LOGIN_LEN = 255
_USER_ATTRS = ["objectSid", "sAMAccountName", "userPrincipalName", "mail", "displayName", "userAccountControl"]
_GROUP_ATTRS = ["objectSid", "cn", "description"]
# 기본 그룹(primary group)은 member/memberOf에 나타나지 않아 따로 찾는다
_PRIMARY_ATTRS = ["objectSid", "primaryGroupID"]


class DirectoryUnavailable(Exception):
    """AD에 연결하거나 서비스 계정으로 bind하지 못했다. 자격 증명 오류와 구분한다."""


@dataclass(frozen=True)
class DirectoryUser:
    dn: str
    sid: str
    username: str
    email: str
    display_name: str
    disabled: bool


@dataclass(frozen=True)
class DirectoryGroup:
    dn: str
    sid: str
    name: str
    description: str | None


@dataclass(frozen=True)
class LdapConfig:
    url: str
    bind_dn: str
    bind_password: str
    base_dn: str
    group_base_dn: str = ""
    start_tls: bool = False
    tls_verify: bool = True
    ca_cert_file: str = ""
    allow_insecure: bool = False
    timeout_seconds: int = 5


class DirectoryClient(Protocol):
    def authenticate(self, login: str, password: str) -> DirectoryUser | None: ...
    def user_groups(self, user_dn: str) -> list[DirectoryGroup]: ...
    def list_users(self) -> list[DirectoryUser]: ...
    def list_groups(self) -> list[DirectoryGroup]: ...


def sid_to_str(value) -> str:
    if isinstance(value, (bytes, bytearray)):
        return format_sid(bytes(value))
    return str(value)


def _entry_sid(entry) -> str:
    """objectSid는 항상 원시 바이트로 읽는다.

    스키마 없이 조회하면 ldap3가 값이 UTF-8로 풀리는 경우에만 문자열로 바꿔 돌려준다. Builtin 그룹
    (S-1-5-32-*)처럼 바이트가 우연히 ASCII인 SID는 그렇게 깨진 문자열이 되므로 raw_attributes를 쓴다.
    """
    raw = (entry.get("raw_attributes") or {}).get("objectSid") or []
    if raw:
        return format_sid(bytes(raw[0]))
    return sid_to_str(_first(entry, "objectSid"))


def _first(entry, attr: str):
    values = entry["attributes"].get(attr)
    if isinstance(values, list):
        return values[0] if values else None
    return values


class LdapDirectoryClient:
    """ldap3로 AD에 접근하는 실제 구현."""

    def __init__(self, config: LdapConfig):
        self._config = config
        secure = config.url.lower().startswith("ldaps://")
        if not secure and not config.start_tls and not config.allow_insecure:
            raise ValueError("LDAP는 ldaps:// 또는 StartTLS로만 연결한다(LDAP_ALLOW_INSECURE는 개발용)")
        tls = ldap3.Tls(
            validate=ssl.CERT_REQUIRED if config.tls_verify else ssl.CERT_NONE,
            ca_certs_file=config.ca_cert_file or None,
        )
        self._server = ldap3.Server(
            config.url, use_ssl=secure, tls=tls, get_info=ldap3.NONE, connect_timeout=config.timeout_seconds
        )

    # -- 연결 ------------------------------------------------------------
    def _connect(self, user: str, password: str) -> ldap3.Connection:
        conn = ldap3.Connection(
            self._server, user=user, password=password, receive_timeout=self._config.timeout_seconds,
            raise_exceptions=False,
        )
        if self._config.start_tls:
            conn.open()
            # raise_exceptions=False라 실패해도 False만 돌려준다. 확인하지 않으면 비밀번호가 평문으로 나간다.
            if not conn.start_tls() or not conn.tls_started:
                conn.unbind()
                raise LDAPStartTLSError("StartTLS failed")
        if not conn.bind():
            conn.unbind()
            raise LDAPBindError(conn.result.get("description", "bind failed"))
        return conn

    def _service(self) -> ldap3.Connection:
        try:
            return self._connect(self._config.bind_dn, self._config.bind_password)
        except LDAPException as exc:
            raise DirectoryUnavailable(f"service bind failed: {type(exc).__name__}") from exc

    def _search(self, conn, base: str, flt: str, attrs: list[str], scope=None) -> list[dict]:
        # 한 번의 search(paged_size=...)는 첫 페이지(500건)만 돌려준다. 사용자가 그보다 많으면
        # 나머지가 "AD에서 사라진 사용자"로 보여 비활성화되므로 반드시 끝까지 넘겨 읽는다.
        entries = conn.extend.standard.paged_search(
            base, flt, search_scope=scope or ldap3.SUBTREE, attributes=attrs, paged_size=_PAGE_SIZE,
            generator=False,
        )
        if conn.result.get("result") not in (0, 32):  # 32 = noSuchObject
            raise DirectoryUnavailable(f"search failed: {conn.result.get('description')}")
        return [e for e in entries or [] if e.get("type") == "searchResEntry"]

    # -- 변환 ------------------------------------------------------------
    def _to_user(self, entry: dict) -> DirectoryUser:
        username = _first(entry, "sAMAccountName") or ""
        upn = _first(entry, "userPrincipalName") or ""
        uac = int(_first(entry, "userAccountControl") or 0)
        return DirectoryUser(
            dn=entry["dn"],
            sid=_entry_sid(entry),
            username=username,
            email=(_first(entry, "mail") or upn or "").lower(),
            display_name=_first(entry, "displayName") or username,
            disabled=bool(uac & _UAC_DISABLED),
        )

    @staticmethod
    def _to_group(entry: dict) -> DirectoryGroup:
        return DirectoryGroup(
            dn=entry["dn"],
            sid=_entry_sid(entry),
            name=_first(entry, "cn") or entry["dn"],
            description=_first(entry, "description"),
        )

    @staticmethod
    def user_filter(login: str) -> str:
        safe = escape_filter_chars(login)
        return (
            "(&(objectCategory=person)(objectClass=user)"
            f"(|(sAMAccountName={safe})(userPrincipalName={safe})(mail={safe})))"
        )

    # -- 공개 API --------------------------------------------------------
    def authenticate(self, login: str, password: str) -> DirectoryUser | None:
        """맞으면 사용자, 자격 증명이 틀리거나 비활성이면 None. AD 장애는 DirectoryUnavailable."""
        login = (login or "").strip()
        if not login or not password or len(login) > _MAX_LOGIN_LEN:
            return None
        conn = self._service()
        try:
            entries = self._search(conn, self._config.base_dn, self.user_filter(login), _USER_ATTRS)
        finally:
            conn.unbind()
        if len(entries) != 1:
            return None
        user = self._to_user(entries[0])
        if user.disabled:
            return None
        try:
            self._connect(user.dn, password).unbind()
        except (LDAPBindError, LDAPPasswordIsMandatoryError):
            return None
        except LDAPException as exc:
            raise DirectoryUnavailable(f"user bind failed: {type(exc).__name__}") from exc
        return user

    def _primary_group(self, conn, user_dn: str) -> DirectoryGroup | None:
        """사용자의 기본 그룹. SID는 사용자 SID의 도메인 부분과 primaryGroupID로 만든다."""
        me = self._search(conn, user_dn, "(objectClass=user)", _PRIMARY_ATTRS, scope=ldap3.BASE)
        if len(me) != 1:
            return None
        rid = _first(me[0], "primaryGroupID")
        user_sid = _entry_sid(me[0])
        if not rid or "-" not in user_sid:
            return None
        group_sid = f"{user_sid.rsplit('-', 1)[0]}-{int(rid)}"
        flt = f"(&(objectClass=group)(objectSid={escape_filter_chars(group_sid)}))"
        found = self._search(conn, self._config.group_base_dn or self._config.base_dn, flt, _GROUP_ATTRS)
        return self._to_group(found[0]) if len(found) == 1 else None

    def user_groups(self, user_dn: str) -> list[DirectoryGroup]:
        conn = self._service()
        try:
            flt = f"(&(objectClass=group)(member:{_IN_CHAIN}:={escape_filter_chars(user_dn)}))"
            entries = self._search(conn, self._config.group_base_dn or self._config.base_dn, flt, _GROUP_ATTRS)
            groups = [self._to_group(e) for e in entries]
            primary = self._primary_group(conn, user_dn)
        finally:
            conn.unbind()
        if primary is not None and primary.sid not in {g.sid for g in groups}:
            groups.append(primary)
        return groups

    def list_users(self) -> list[DirectoryUser]:
        conn = self._service()
        try:
            entries = self._search(
                conn, self._config.base_dn, "(&(objectCategory=person)(objectClass=user))", _USER_ATTRS
            )
        finally:
            conn.unbind()
        return [self._to_user(e) for e in entries]

    def list_groups(self) -> list[DirectoryGroup]:
        conn = self._service()
        try:
            entries = self._search(
                conn, self._config.group_base_dn or self._config.base_dn, "(objectClass=group)", _GROUP_ATTRS
            )
        finally:
            conn.unbind()
        return [self._to_group(e) for e in entries]
