"""v3 마일스톤 3 — AD 계정 자동 생성과 그룹·비활성 동기화.

AD가 기준이다. 로그인할 때와 주기 동기화 때 사용자 상태와 AD 그룹 구성원을 AD에 맞춘다.
화면에서 정한 열람등급과 로컬 그룹 구성원은 건드리지 않는다.
"""
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.db.models.user import User
from app.db.models.user_group import UserGroup, UserGroupMember
from app.services.directory.ldap_client import DirectoryGroup, DirectoryUnavailable, DirectoryUser
from app.services.directory.provisioning import (
    DirectoryConflict,
    provision_login,
    sync_directory,
)
from tests.unit.api_pg_helpers import db_session, make_user  # noqa: F401

pytestmark = pytest.mark.asyncio

ADMIN_DN = "CN=docvec-admins,CN=Users,DC=t"
DOMAIN = "S-1-5-21-9-9-9"


def _user(name, rid, *, email=None, disabled=False):
    return DirectoryUser(
        dn=f"CN={name},CN=Users,DC=t", sid=f"{DOMAIN}-{rid}", username=name,
        email=email if email is not None else f"{name}@corp.test", display_name=f"{name} 님", disabled=disabled,
    )


def _group(name, rid):
    return DirectoryGroup(dn=f"CN={name},CN=Users,DC=t", sid=f"{DOMAIN}-{rid}", name=name, description=None)


SALES, EAST, RESEARCH, ADMINS = (
    _group("sales", 1101), _group("sales-east", 1102), _group("research", 1103), _group("docvec-admins", 1104)
)
ADMINS = DirectoryGroup(dn=ADMIN_DN, sid=ADMINS.sid, name=ADMINS.name, description=None)


class FakeDirectory:
    def __init__(self, users, groups, memberships):
        self.users, self.groups, self.memberships = users, groups, memberships
        self.down = False

    def _check(self):
        if self.down:
            raise DirectoryUnavailable("down")

    def list_users(self):
        self._check()
        return list(self.users)

    def list_groups(self):
        self._check()
        return list(self.groups)

    def user_groups(self, dn):
        self._check()
        return list(self.memberships.get(dn, []))


async def _login(db, duser, groups):
    user = await db.run_sync(lambda s: provision_login(s, duser, groups, ADMIN_DN))
    await db.commit()
    return user


async def _group_names(db, user_id):
    rows = await db.execute(
        select(UserGroup.name).join(UserGroupMember, UserGroupMember.group_id == UserGroup.id)
        .where(UserGroupMember.user_id == user_id)
    )
    return sorted(rows.scalars().all())


async def test_first_login_creates_viewer_with_groups(db_session):  # noqa: F811
    alice = _user("alice", 2001)
    user = await _login(db_session, alice, [SALES, EAST])

    assert (user.auth_source, user.external_id, user.role, user.clearance_level, user.is_active) == (
        "ldap", alice.sid, "viewer", "Internal", True,
    )
    assert user.email == "alice@corp.test" and user.username == "alice 님"
    assert await _group_names(db_session, user.id) == ["sales", "sales-east"]
    groups = (await db_session.scalars(select(UserGroup).where(UserGroup.source == "ldap"))).all()
    assert {g.external_id for g in groups} >= {SALES.sid, EAST.sid}


async def test_relogin_updates_ad_groups_but_keeps_local_groups_and_clearance(db_session):  # noqa: F811
    alice = _user("alice", 2002)
    user = await _login(db_session, alice, [SALES, EAST])
    local = UserGroup(id=str(uuid4()), name=f"local-{uuid4().hex[:6]}")
    db_session.add(local)
    await db_session.flush()
    db_session.add(UserGroupMember(group_id=local.id, user_id=user.id))
    user.clearance_level = "Confidential"
    await db_session.commit()

    user = await _login(db_session, alice, [RESEARCH])

    assert await _group_names(db_session, user.id) == sorted([local.name, "research"])
    assert user.clearance_level == "Confidential"


async def test_admin_role_follows_admin_group_and_manual_editor_is_kept(db_session):  # noqa: F811
    carol = _user("carol", 2003)
    user = await _login(db_session, carol, [ADMINS])
    assert user.role == "admin"

    user = await _login(db_session, carol, [])
    assert user.role == "viewer"  # 관리자 그룹에서 빠지면 관리자 권한도 잃는다

    user.role = "editor"
    await db_session.commit()
    user = await _login(db_session, carol, [])
    assert user.role == "editor"


async def test_local_account_with_same_email_is_not_merged(db_session):  # noqa: F811
    local = await make_user(db_session)
    await db_session.commit()
    local_id = local.id
    bob = _user("bob", 2004, email=local.email)

    with pytest.raises(DirectoryConflict):
        await db_session.run_sync(lambda s: provision_login(s, bob, [], ADMIN_DN))
    await db_session.rollback()

    refreshed = await db_session.get(User, local_id)
    assert refreshed.auth_source == "local" and refreshed.external_id is None


async def test_user_without_mail_gets_placeholder_email(db_session):  # noqa: F811
    dave = _user("dave2", 2005, email="")
    user = await _login(db_session, dave, [])
    assert user.email == "dave2.2005@directory.invalid"


async def test_ad_group_name_colliding_with_local_group_gets_suffix(db_session):  # noqa: F811
    name = f"dup-{uuid4().hex[:6]}"
    db_session.add(UserGroup(id=str(uuid4()), name=name))
    await db_session.commit()

    user = await _login(db_session, _user("erin", 2006), [_group(name, 1199)])
    assert await _group_names(db_session, user.id) == [f"{name} (AD)"]


async def test_sync_disables_removed_or_disabled_users_and_drops_removed_groups(db_session):  # noqa: F811
    alice, bob, frank = _user("alice3", 2101), _user("bob3", 2102), _user("frank3", 2103)
    gone = _group("gone", 1201)
    for u, gs in ((alice, [SALES]), (bob, [RESEARCH]), (frank, [gone])):
        await _login(db_session, u, gs)

    directory = FakeDirectory(
        users=[alice, _user("bob3", 2102, disabled=True)],  # frank는 AD에서 지워졌다
        groups=[SALES, EAST, RESEARCH],
        memberships={alice.dn: [SALES, EAST]},
    )
    result = await db_session.run_sync(lambda s: sync_directory(s, directory, ADMIN_DN))
    await db_session.commit()

    by_sid = {
        u.external_id: u for u in (await db_session.scalars(
            select(User).where(User.external_id.in_([alice.sid, bob.sid, frank.sid]))
        )).all()
    }
    assert by_sid[alice.sid].is_active is True
    assert by_sid[bob.sid].is_active is False and by_sid[frank.sid].is_active is False
    assert await _group_names(db_session, by_sid[alice.sid].id) == ["sales", "sales-east"]
    assert await db_session.scalar(select(UserGroup).where(UserGroup.external_id == gone.sid)) is None
    assert result["deactivated"] >= 2 and result["groups_removed"] >= 1


async def test_sync_changes_nothing_when_directory_is_unavailable(db_session):  # noqa: F811
    alice = _user("alice4", 2201)
    user = await _login(db_session, alice, [SALES])
    directory = FakeDirectory([alice], [SALES], {})
    directory.down = True

    with pytest.raises(DirectoryUnavailable):
        await db_session.run_sync(lambda s: sync_directory(s, directory, ADMIN_DN))
    await db_session.rollback()

    refreshed = await db_session.get(User, user.id)
    assert refreshed.is_active is True
    assert await _group_names(db_session, user.id) == ["sales"]


async def test_sync_refuses_empty_directory_instead_of_disabling_everyone(db_session):  # noqa: F811
    # 잘못된 base DN 같은 설정 실수로 AD가 0명을 돌려주면 전원을 비활성화하지 않고 멈춘다.
    user_id = (await _login(db_session, _user("alice5", 2301), [SALES])).id

    with pytest.raises(DirectoryUnavailable):
        await db_session.run_sync(lambda s: sync_directory(s, FakeDirectory([], [], {}), ADMIN_DN))
    await db_session.rollback()
    assert (await db_session.get(User, user_id)).is_active is True


async def test_sync_does_not_touch_local_users(db_session):  # noqa: F811
    local = await make_user(db_session)
    await db_session.commit()
    other = _user("someone", 2401)
    await db_session.run_sync(lambda s: sync_directory(s, FakeDirectory([other], [], {}), ADMIN_DN))
    await db_session.commit()
    assert (await db_session.get(User, local.id)).is_active is True


async def test_sync_refuses_to_deactivate_most_users_at_once(db_session):  # noqa: F811
    # 검색 결과가 잘리거나 검색 범위가 바뀌어 대부분이 "사라진" 것처럼 보이면 비활성화하지 않고 멈춘다.
    users = [_user(f"bulk{i}", 2400 + i) for i in range(6)]
    ids = [(await _login(db_session, u, [SALES])).id for u in users]
    directory = FakeDirectory(users[:1], [SALES], {users[0].dn: [SALES]})

    with pytest.raises(DirectoryUnavailable, match="refusing to deactivate"):
        await db_session.run_sync(lambda s: sync_directory(s, directory, ADMIN_DN))
    await db_session.rollback()
    assert all([(await db_session.get(User, i)).is_active for i in ids])
