"""v3 마일스톤 3 — 로그인의 AD(LDAP) 경로.

로컬 계정은 지금처럼 비밀번호 해시로 확인한다. 그 밖의 아이디는 AD로 확인하고, 성공하면 계정을
자동으로 만든다. AD에 연결하지 못하면 503으로 거부한다(캐시된 자격 증명으로 통과시키지 않는다).
"""
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api.v1.endpoints import auth as auth_module
from app.core.security import get_password_hash
from app.db.models.audit_log import AuditLog
from app.db.models.user import User
from app.schemas.auth import LoginRequest
from app.services.directory.ldap_client import DirectoryGroup, DirectoryUnavailable, DirectoryUser
from tests.unit.api_pg_helpers import db_session  # noqa: F401

pytestmark = pytest.mark.asyncio

_no_rate_limit = patch.object(auth_module, "enforce_rate_limit", MagicMock())
PASSWORD = "correct horse battery"


def _http_request():
    req = MagicMock()
    req.client.host = "127.0.0.1"
    return req


class FakeDirectory:
    def __init__(self, user=None, groups=(), down=False):
        self.user, self.groups, self.down = user, list(groups), down
        self.calls = []

    def authenticate(self, login, password):
        self.calls.append(login)
        if self.down:
            raise DirectoryUnavailable("down")
        return self.user if password == PASSWORD else None

    def user_groups(self, dn):
        return self.groups


def _duser(name):
    rid = uuid4().int % 100000
    return DirectoryUser(
        dn=f"CN={name},DC=t", sid=f"S-1-5-21-7-7-7-{rid}", username=name,
        email=f"{name}-{rid}@corp.test", display_name=name, disabled=False,
    )


async def _login(db, login, password, directory):
    with _no_rate_limit, patch.object(auth_module, "get_directory_client", lambda: directory):
        return await auth_module.login(
            LoginRequest(email=login, password=password), MagicMock(), _http_request(), db
        )


async def _audits(db, action):
    return (await db.scalars(select(AuditLog).where(AuditLog.action == action))).all()


async def test_directory_login_creates_account_and_is_audited(db_session):  # noqa: F811
    duser = _duser("alice")
    group = DirectoryGroup(dn="CN=sales,DC=t", sid=f"{duser.sid}-g", name=f"sales-{uuid4().hex[:4]}", description=None)

    result = await _login(db_session, "alice", PASSWORD, FakeDirectory(duser, [group]))

    assert result.access_token and result.user.email == duser.email
    user = await db_session.scalar(select(User).where(User.external_id == duser.sid))
    assert user.auth_source == "ldap" and user.role == "viewer"
    rows = [r for r in await _audits(db_session, "auth.login") if str(r.user_id) == str(user.id)]
    assert rows and rows[0].detail == {"source": "ldap"}


async def test_directory_login_with_wrong_password_is_401_and_audited(db_session):  # noqa: F811
    login = f"nobody-{uuid4().hex[:6]}"
    with pytest.raises(HTTPException) as exc:
        await _login(db_session, login, "wrong-password", FakeDirectory(_duser("x")))
    assert exc.value.status_code == 401
    assert any((r.detail or {}).get("email") == login for r in await _audits(db_session, "auth.login_failed"))


async def test_directory_outage_is_503_not_a_silent_pass(db_session):  # noqa: F811
    with pytest.raises(HTTPException) as exc:
        await _login(db_session, "alice", PASSWORD, FakeDirectory(down=True))
    assert exc.value.status_code == 503


async def test_local_account_still_logs_in_without_touching_the_directory(db_session):  # noqa: F811
    email = f"local-{uuid4().hex[:6]}@example.com"
    db_session.add(User(id=str(uuid4()), email=email, username="local", role="admin",
                        hashed_password=get_password_hash(PASSWORD), is_active=True))
    await db_session.commit()
    directory = FakeDirectory(down=True)

    result = await _login(db_session, email, PASSWORD, directory)

    assert result.user.email == email and directory.calls == []


async def test_directory_account_cannot_use_local_password_path(db_session):  # noqa: F811
    duser = _duser("bob")
    await _login(db_session, "bob", PASSWORD, FakeDirectory(duser))

    # AD가 비밀번호를 거부하면, 이메일로 로그인해도 로컬 해시 검사로 넘어가지 않는다
    with pytest.raises(HTTPException) as exc:
        await _login(db_session, duser.email, "another-password", FakeDirectory(duser))
    assert exc.value.status_code == 401


async def test_system_account_can_never_log_in(db_session):  # noqa: F811
    email = f"connector-{uuid4().hex[:6]}@system.invalid"
    db_session.add(User(id=str(uuid4()), email=email, username="connector", role="viewer",
                        hashed_password="!system", auth_source="system", is_active=True))
    await db_session.commit()

    with pytest.raises(HTTPException) as exc:
        await _login(db_session, email, PASSWORD, FakeDirectory(_duser("y")))
    assert exc.value.status_code == 401


async def test_same_email_local_account_blocks_directory_login(db_session):  # noqa: F811
    duser = _duser("carol")
    db_session.add(User(id=str(uuid4()), email=duser.email, username="local carol", role="viewer",
                        hashed_password=get_password_hash("local-password-1"), is_active=True))
    await db_session.commit()

    # 아이디로 로그인하면 로컬 계정을 찾지 못해 AD로 간다. 같은 이메일의 로컬 계정과 합치지 않는다.
    with pytest.raises(HTTPException) as exc:
        await _login(db_session, "carol", PASSWORD, FakeDirectory(duser))
    assert exc.value.status_code == 409


async def test_unknown_login_is_401_when_directory_login_is_off(db_session):  # noqa: F811
    with pytest.raises(HTTPException) as exc:
        await _login(db_session, "alice", PASSWORD, None)
    assert exc.value.status_code == 401


def test_login_request_accepts_plain_username():
    assert LoginRequest(email="alice", password="x").email == "alice"
    with pytest.raises(ValueError):
        LoginRequest(email="alice", password="")


def test_object_sid_is_read_from_raw_bytes_even_when_it_looks_like_text():
    # S-1-5-32-544(BUILTINAdministrators)의 바이트는 우연히 ASCII라 ldap3가 문자열로 풀어 버린다
    from app.services.directory.ldap_client import LdapDirectoryClient

    raw = bytes.fromhex("01020000000000052000000020020000")
    entry = {
        "dn": "CN=Administrators,CN=Builtin,DC=corp,DC=local",
        "attributes": {"objectSid": raw.decode("ascii"), "cn": "Administrators"},
        "raw_attributes": {"objectSid": [raw]},
    }
    assert LdapDirectoryClient._to_group(entry).sid == "S-1-5-32-544"


async def test_self_registration_is_closed_when_directory_login_is_on(db_session, monkeypatch):  # noqa: F811
    # 열어 두면 아직 로그인하지 않은 직원의 이메일로 로컬 계정을 먼저 만들어 AD 로그인을 가로챌 수 있다
    from app.schemas.auth import UserCreate

    monkeypatch.setattr(auth_module.settings, "ldap_enabled", True)
    body = UserCreate(email=f"victim-{uuid4().hex[:6]}@example.com", username="victim", password="password123!")
    with _no_rate_limit, pytest.raises(HTTPException) as exc:
        await auth_module.register(body, MagicMock(), _http_request(), db_session)
    assert exc.value.status_code == 403


def test_failed_start_tls_never_sends_the_password():
    from app.services.directory import ldap_client

    conn = MagicMock()
    conn.start_tls.return_value = False
    conn.tls_started = False
    client = ldap_client.LdapDirectoryClient(ldap_client.LdapConfig(
        url="ldap://dc:389", start_tls=True, bind_dn="svc", bind_password="pw", base_dn="DC=t",
    ))
    with patch.object(ldap_client.ldap3, "Connection", return_value=conn), pytest.raises(DirectoryUnavailable):
        client._service()
    conn.bind.assert_not_called()


def test_directory_search_reads_every_page():
    from app.services.directory import ldap_client

    conn = MagicMock()
    conn.extend.standard.paged_search.return_value = [
        {"type": "searchResEntry", "dn": f"CN=u{i}"} for i in range(1200)
    ] + [{"type": "searchResRef"}]
    conn.result = {"result": 0}
    client = ldap_client.LdapDirectoryClient(ldap_client.LdapConfig(
        url="ldaps://dc:636", bind_dn="svc", bind_password="pw", base_dn="DC=t",
    ))
    entries = client._search(conn, "DC=t", "(objectClass=user)", ["cn"])
    assert len(entries) == 1200
    assert conn.extend.standard.paged_search.call_args.kwargs["generator"] is False


def test_user_groups_include_the_primary_group_that_member_of_does_not_list():
    from app.services.directory import ldap_client

    client = ldap_client.LdapDirectoryClient(ldap_client.LdapConfig(
        url="ldaps://dc:636", bind_dn="svc", bind_password="pw", base_dn="DC=t",
    ))
    chain = [{"dn": "CN=sales,DC=t", "attributes": {"cn": "sales", "objectSid": "S-1-5-21-1-2-3-1101"}}]
    me = [{"dn": "CN=amy,DC=t", "attributes": {"objectSid": "S-1-5-21-1-2-3-2001", "primaryGroupID": 1150}}]
    primary = [{"dn": "CN=field,DC=t", "attributes": {"cn": "field", "objectSid": "S-1-5-21-1-2-3-1150"}}]
    calls = []

    def fake_search(conn, base, flt, attrs, scope=None):
        calls.append(flt)
        if "member:" in flt:
            return chain
        if "objectSid=" in flt:
            return primary
        return me

    client._service = MagicMock()
    client._search = fake_search
    groups = client.user_groups("CN=amy,DC=t")

    assert [g.name for g in groups] == ["sales", "field"]
    assert any("(objectSid=S-1-5-21-1-2-3-1150)" in f for f in calls)
