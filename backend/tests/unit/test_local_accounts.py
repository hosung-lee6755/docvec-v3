"""AD가 없는 회사의 계정 관리: 관리자 계정 발급, 비밀번호 초기화, CSV 일괄 등록(실제 Postgres, SAVEPOINT 롤백)."""
import io
from datetime import datetime
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from starlette.datastructures import UploadFile

from app.api.v1.endpoints import user_accounts as accounts_api
from app.core.config import settings
from app.core.security import verify_password
from app.db.models.access_token import PersonalAccessToken
from app.db.models.user import AUTH_SOURCE_LDAP, User
from app.db.models.user_group import UserGroup, UserGroupMember
from app.services import local_accounts as la
from tests.unit.api_pg_helpers import db_session, make_user  # noqa: F401

CSV_HEADER = "email,username,role,clearance_level,groups\n"


async def _group(db, name: str, source: str = "local") -> UserGroup:
    group = UserGroup(id=uuid4(), name=name, source=source)
    db.add(group)
    await db.flush()
    return group


def _upload(text: str) -> UploadFile:
    return UploadFile(file=io.BytesIO(text.encode("utf-8")), filename="users.csv")


# ------------------------------------------------------------ 임시 비밀번호
def test_temporary_password_is_long_mixed_and_unique():
    first, second = la.generate_temporary_password(), la.generate_temporary_password()
    assert len(first) >= 12 and first != second
    assert any(c.isdigit() for c in first) and any(c.isalpha() for c in first)


# ------------------------------------------------------------ 계정 발급
@pytest.mark.asyncio
async def test_admin_creates_a_local_account_that_must_change_its_temporary_password(db_session):  # noqa: F811
    admin = await make_user(db_session, "admin")

    user, temporary = await la.create_local_account(
        db_session, email="  Kim@Corp.Local ", username="김직원", role="editor", clearance_level="Confidential",
        actor=admin,
    )

    assert user.email == "kim@corp.local"
    assert user.role == "editor" and user.clearance_level == "Confidential"
    assert user.auth_source == "local" and user.must_change_password is True
    assert verify_password(temporary, user.hashed_password)


@pytest.mark.asyncio
async def test_creating_an_account_with_an_existing_email_is_refused_regardless_of_case(db_session):  # noqa: F811
    admin = await make_user(db_session, "admin")
    await la.create_local_account(db_session, email="lee@corp.local", username="이", actor=admin)

    with pytest.raises(la.AccountError, match="이미 쓰는 이메일"):
        await la.create_local_account(db_session, email="LEE@corp.local", username="이2", actor=admin)


# ------------------------------------------------------------ 비밀번호 초기화
@pytest.mark.asyncio
async def test_reset_issues_a_new_temporary_password_and_ends_existing_sessions_and_agent_tokens(db_session):  # noqa: F811
    admin = await make_user(db_session, "admin")
    user, old = await la.create_local_account(db_session, email="park@corp.local", username="박", actor=admin)
    user.must_change_password = False
    token = PersonalAccessToken(
        id=uuid4(), user_id=user.id, name="노트북", token_prefix="dvp_abcd", token_hash="h" * 64,
        expires_at=datetime(2099, 1, 1),
    )
    db_session.add(token)
    await db_session.flush()
    version_before = user.token_version

    temporary = await la.reset_local_password(db_session, user, actor=admin)

    assert temporary != old and verify_password(temporary, user.hashed_password)
    assert user.must_change_password is True
    assert user.token_version == version_before + 1
    await db_session.refresh(token)
    assert token.revoked_at is not None


@pytest.mark.asyncio
async def test_directory_accounts_cannot_be_reset_here(db_session):  # noqa: F811
    admin = await make_user(db_session, "admin")
    directory_user = await make_user(db_session)
    directory_user.auth_source = AUTH_SOURCE_LDAP

    with pytest.raises(la.AccountError, match="AD"):
        await la.reset_local_password(db_session, directory_user, actor=admin)


# ------------------------------------------------------------ CSV 해석
def test_csv_accepts_korean_headers_bom_and_semicolon_separated_groups():
    content = "﻿이메일,이름,역할,열람등급,그룹\nA@corp.local,가,editor,Internal,영업팀; 기획팀\nb@corp.local,나,,,\n"

    rows, problems = la.parse_user_csv(content.encode("utf-8"))

    assert problems == []
    assert rows[0] == la.ImportRow(line=2, email="a@corp.local", username="가", role="editor",
                                   clearance_level="Internal", groups=("영업팀", "기획팀"))
    assert rows[1].role == "viewer" and rows[1].clearance_level is None and rows[1].groups == ()


def test_csv_reports_every_bad_row_with_its_line_number():
    content = (CSV_HEADER + ",빈메일,viewer,,\nnot-an-email,가,viewer,,\nc@corp.local,다,owner,,\n"
               "d@corp.local,라,viewer,TopSecret,\ne@corp.local,마,viewer,,\ne@corp.local,중복,viewer,,\n")

    _, problems = la.parse_user_csv(content.encode("utf-8"))

    by_line = {p.line: p.message for p in problems}
    assert "이메일" in by_line[2]
    assert "이메일 형식" in by_line[3]
    assert "역할" in by_line[4]
    assert "열람등급" in by_line[5]
    assert 6 not in by_line
    assert "중복" in by_line[7]


def test_csv_without_an_email_column_is_rejected():
    _, problems = la.parse_user_csv("name,role\n가,viewer\n".encode("utf-8"))
    assert problems and problems[0].line == 1


def test_csv_that_is_not_utf8_is_rejected_with_a_hint():
    _, problems = la.parse_user_csv("email,username\na@b.c,가\n".encode("cp949"))
    assert "UTF-8" in problems[0].message


# ------------------------------------------------------------ 일괄 등록
@pytest.mark.asyncio
async def test_import_creates_every_account_and_adds_them_to_local_groups(db_session):  # noqa: F811
    admin = await make_user(db_session, "admin")
    sales = await _group(db_session, f"영업팀-{uuid4().hex[:6]}")
    rows, _ = la.parse_user_csv(
        (CSV_HEADER + f"x1@corp.local,가,viewer,,{sales.name}\nx2@corp.local,나,editor,Internal,\n").encode("utf-8"))

    created = await la.import_local_accounts(db_session, rows, actor=admin)

    assert [u.email for u, _ in created] == ["x1@corp.local", "x2@corp.local"]
    assert all(u.must_change_password for u, _ in created)
    member = await db_session.get(UserGroupMember, (sales.id, created[0][0].id))
    assert member is not None


@pytest.mark.asyncio
async def test_import_creates_nothing_when_any_row_conflicts(db_session):  # noqa: F811
    admin = await make_user(db_session, "admin")
    await la.create_local_account(db_session, email="taken@corp.local", username="기존", actor=admin)
    directory_group = await _group(db_session, f"AD그룹-{uuid4().hex[:6]}", source="ldap")
    rows, _ = la.parse_user_csv(
        (CSV_HEADER + "new@corp.local,새,viewer,,없는그룹\nTAKEN@corp.local,중복,viewer,,\n"
         f"new2@corp.local,새2,viewer,,{directory_group.name}\n").encode("utf-8"))

    with pytest.raises(la.AccountImportError) as exc:
        await la.import_local_accounts(db_session, rows, actor=admin)

    messages = {p.line: p.message for p in exc.value.problems}
    assert "없는그룹" in messages[2]
    assert "이미 쓰는 이메일" in messages[3]
    assert "AD" in messages[4]
    assert await db_session.scalar(select(User).where(User.email == "new@corp.local")) is None


# ------------------------------------------------------------ API
@pytest.mark.asyncio
async def test_api_create_and_reset_are_admin_only_and_return_the_temporary_password_once(db_session):  # noqa: F811
    admin, viewer = await make_user(db_session, "admin"), await make_user(db_session)
    body = accounts_api.AccountCreate(email="api@corp.local", username="에이피아이", role="viewer")

    with pytest.raises(HTTPException) as denied:
        await accounts_api.create_account(body, db_session, viewer)
    assert denied.value.status_code == 403

    created = await accounts_api.create_account(body, db_session, admin)
    assert created.user.email == "api@corp.local" and created.temporary_password

    reset = await accounts_api.reset_password(created.user.id, db_session, admin)
    assert reset.temporary_password and reset.temporary_password != created.temporary_password


@pytest.mark.asyncio
async def test_api_refuses_local_accounts_while_directory_login_is_on(db_session, monkeypatch):  # noqa: F811
    admin = await make_user(db_session, "admin")
    monkeypatch.setattr(settings, "ldap_enabled", True)

    with pytest.raises(HTTPException) as exc:
        await accounts_api.create_account(
            accounts_api.AccountCreate(email="ad@corp.local", username="에이디"), db_session, admin)
    assert exc.value.status_code == 409 and "AD" in exc.value.detail

    with pytest.raises(HTTPException) as bulk:
        await accounts_api.import_accounts(_upload(CSV_HEADER + "z@corp.local,가,viewer,,\n"), db_session, admin)
    assert bulk.value.status_code == 409


@pytest.mark.asyncio
async def test_api_import_reports_problems_by_line_and_creates_nothing(db_session):  # noqa: F811
    admin = await make_user(db_session, "admin")

    with pytest.raises(HTTPException) as exc:
        await accounts_api.import_accounts(_upload(CSV_HEADER + "ok@corp.local,가,viewer,,\nbad,나,viewer,,\n"),
                                           db_session, admin)

    assert exc.value.status_code == 422
    assert exc.value.detail["problems"] == [{"line": 3, "message": "이메일 형식이 올바르지 않습니다: bad"}]
    assert await db_session.scalar(select(User).where(User.email == "ok@corp.local")) is None

    result = await accounts_api.import_accounts(_upload(CSV_HEADER + "ok@corp.local,가,viewer,,\n"), db_session, admin)
    assert result.count == 1 and result.created[0].temporary_password


@pytest.mark.asyncio
async def test_api_rejects_files_that_are_too_large(db_session, monkeypatch):  # noqa: F811
    admin = await make_user(db_session, "admin")
    monkeypatch.setattr(accounts_api, "MAX_IMPORT_BYTES", 10)

    with pytest.raises(HTTPException) as exc:
        await accounts_api.import_accounts(_upload(CSV_HEADER), db_session, admin)
    assert exc.value.status_code == 413


# ------------------------------------------------------------ AD 계정으로 전환과 즉시 동기화
@pytest.mark.asyncio
async def test_linking_a_local_account_to_ad_ends_its_password_and_sessions(db_session, monkeypatch):  # noqa: F811
    admin = await make_user(db_session, "admin")
    user, _ = await la.create_local_account(db_session, email="link@corp.local", username="전환", actor=admin)
    token = PersonalAccessToken(
        id=uuid4(), user_id=user.id, name="노트북", token_prefix="dvp_link", token_hash="l" * 64,
        expires_at=datetime(2099, 1, 1),
    )
    db_session.add(token)
    await db_session.flush()
    version = user.token_version
    monkeypatch.setattr(settings, "ldap_enabled", True)

    out = await accounts_api.link_directory(user.id, db_session, admin)

    assert out.auth_source == "ldap"
    assert user.external_id is None and user.must_change_password is False
    assert user.token_version == version + 1 and not user.hashed_password.startswith("$")
    await db_session.refresh(token)
    assert token.revoked_at is not None


@pytest.mark.asyncio
async def test_linking_requires_directory_login_and_refuses_yourself(db_session, monkeypatch):  # noqa: F811
    admin = await make_user(db_session, "admin")
    user, _ = await la.create_local_account(db_session, email="link2@corp.local", username="전환2", actor=admin)

    monkeypatch.setattr(settings, "ldap_enabled", False)
    with pytest.raises(HTTPException) as off:
        await accounts_api.link_directory(user.id, db_session, admin)
    assert off.value.status_code == 409

    monkeypatch.setattr(settings, "ldap_enabled", True)
    with pytest.raises(HTTPException) as own:
        await accounts_api.link_directory(admin.id, db_session, admin)
    assert own.value.status_code == 409


@pytest.mark.asyncio
async def test_directory_sync_can_be_requested_now_by_admins(db_session, monkeypatch):  # noqa: F811
    from unittest.mock import MagicMock

    admin, viewer = await make_user(db_session, "admin"), await make_user(db_session)
    monkeypatch.setattr(settings, "ldap_enabled", True)
    task = MagicMock()
    monkeypatch.setattr("app.pipeline.tasks.directory.sync_directory_task", task)

    with pytest.raises(HTTPException):
        await accounts_api.sync_directory_now(db_session, viewer)
    out = await accounts_api.sync_directory_now(db_session, admin)

    assert out["status"] == "queued"
    task.delay.assert_called_once()
