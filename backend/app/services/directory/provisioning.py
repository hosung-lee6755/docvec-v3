"""AD 계정 자동 생성과 그룹·비활성 동기화(v3 마일스톤 3).

AD가 기준이다.
- 로그인(`provision_login`): 사용자를 만들거나 갱신하고, 그 사용자의 AD 그룹 구성원을 AD에 맞춘다.
- 주기 동기화(`sync_directory`): AD 그룹 목록을 맞추고, AD에서 사라지거나 비활성화된 사용자를
  비활성 처리한다. 아직 로그인하지 않은 AD 사용자도 미리 만들어, 컬렉션 공유와 파일 권한 매핑에 쓸 수 있게 한다.
- 같은 이메일의 로컬 계정은 합치지 않는다. 관리자가 "AD 계정으로 전환"해 둔 계정(auth_source=ldap,
  external_id 없음)만 첫 AD 로그인이나 동기화 때 이어받는다.
- AD에서 지웠다가 같은 이름으로 다시 만든 그룹은 SID가 달라 다른 주체다. 옛 그룹의 권한을 넘기지 않고
  동기화 결과(recreated_groups)로 알려 관리자가 다시 주게 한다.

화면에서 정한 열람등급, 직접 준 editor 역할, 로컬 그룹 구성원은 건드리지 않는다. 관리자 역할만은
AD의 관리자 그룹(`LDAP_ADMIN_GROUP_DN`)을 따른다. 동기화 함수는 sync Session을 받는다.
비동기 엔드포인트에서는 `AsyncSession.run_sync`로 부른다.
"""
from __future__ import annotations

from uuid import uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db.models.user import AUTH_SOURCE_LDAP, User
from app.db.models.user_group import GROUP_SOURCE_LDAP, UserGroup, UserGroupMember
from app.services.directory.ldap_client import (
    DirectoryClient,
    DirectoryGroup,
    DirectoryUnavailable,
    DirectoryUser,
)

PLACEHOLDER_EMAIL_DOMAIN = "directory.invalid"
# 해시 형식이 아니므로 어떤 비밀번호도 맞지 않는다. 로그인은 auth_source로 먼저 갈라진다.
UNUSABLE_PASSWORD = "!directory-account"
_MAX_NAME = 255
# 감사 로그에 남길 충돌 이메일 수
_MAX_REPORTED = 20


class DirectoryConflict(Exception):
    """같은 이메일의 로컬 계정이 있어 AD 계정을 만들 수 없다. 관리자가 정리해야 한다."""


def _rid(sid: str) -> str:
    return sid.rsplit("-", 1)[-1]


def _email_for(duser: DirectoryUser) -> str:
    if duser.email:
        return duser.email.lower()[:_MAX_NAME]
    return f"{duser.username.lower()}.{_rid(duser.sid)}@{PLACEHOLDER_EMAIL_DOMAIN}"


def normalize_dn(dn: str | None) -> str:
    """DN 비교용 정규형. AD는 대소문자와 구분자 주변 공백을 가리지 않는다."""
    parts = (dn or "").strip().split(",")
    return ",".join("=".join(piece.strip() for piece in part.split("=")) for part in parts).lower()


def _is_admin(groups: list[DirectoryGroup], admin_group_dn: str) -> bool:
    target = normalize_dn(admin_group_dn)
    return bool(target) and any(normalize_dn(g.dn) == target for g in groups)


# -- 그룹 -----------------------------------------------------------------

def _free_group_name(db: Session, wanted: str, own_id) -> str:
    """AD 그룹 이름이 로컬 그룹과 겹치면 "(AD)"를 붙인다. 그래도 겹치면 짧은 접미어를 더한다."""
    for name in (wanted[:_MAX_NAME], f"{wanted[:_MAX_NAME - 5]} (AD)"):
        holder = db.scalar(select(UserGroup).where(UserGroup.name == name))
        if holder is None or str(holder.id) == str(own_id):
            return name
    return f"{wanted[:_MAX_NAME - 20]} (AD {uuid4().hex[:8]})"


def _upsert_groups(db: Session, groups: list[DirectoryGroup]) -> dict[str, UserGroup]:
    unique = {g.sid: g for g in groups}
    if not unique:
        return {}
    rows = {
        g.external_id: g
        for g in db.scalars(select(UserGroup).where(UserGroup.external_id.in_(list(unique))))
    }
    for sid, dgroup in unique.items():
        row = rows.get(sid)
        if row is None:
            row = UserGroup(
                id=uuid4(), source=GROUP_SOURCE_LDAP, external_id=sid,
                name=_free_group_name(db, dgroup.name, None),
            )
            db.add(row)
            rows[sid] = row
        else:
            row.name = _free_group_name(db, dgroup.name, row.id)
        row.external_dn = dgroup.dn
        row.description = dgroup.description
        db.flush()
    return rows


def _set_directory_memberships(db: Session, user: User, groups: list[UserGroup]) -> None:
    """AD 출처 그룹의 구성원만 맞춘다. 로컬 그룹 구성원은 그대로 둔다."""
    target = {str(g.id) for g in groups}
    current = {
        str(gid)
        for gid in db.scalars(
            select(UserGroupMember.group_id)
            .join(UserGroup, UserGroup.id == UserGroupMember.group_id)
            .where(UserGroupMember.user_id == user.id, UserGroup.source == GROUP_SOURCE_LDAP)
        )
    }
    stale = current - target
    if stale:
        db.execute(
            delete(UserGroupMember).where(
                UserGroupMember.user_id == user.id, UserGroupMember.group_id.in_(list(stale))
            )
        )
    for gid in target - current:
        db.add(UserGroupMember(group_id=gid, user_id=user.id))
    db.flush()


# -- 사용자 ---------------------------------------------------------------

def _same_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(func.lower(User.email) == email).limit(1))


def _is_pending_link(user: User | None) -> bool:
    """관리자가 AD 계정으로 전환해 두고 아직 AD 사용자와 이어지지 않은 계정."""
    return user is not None and user.auth_source == AUTH_SOURCE_LDAP and not user.external_id


def _upsert_user(db: Session, duser: DirectoryUser, groups: list[DirectoryGroup], admin_group_dn: str) -> User:
    email = _email_for(duser)
    user = db.scalar(select(User).where(User.external_id == duser.sid))
    clash = _same_email(db, email)
    if user is None and _is_pending_link(clash):
        user, clash = clash, None
        user.external_id = duser.sid
    if user is None:
        if clash is not None:
            raise DirectoryConflict(f"email already used by another account: {email}")
        user = User(
            id=uuid4(), email=email, username=(duser.display_name or duser.username)[:_MAX_NAME],
            hashed_password=UNUSABLE_PASSWORD, role="viewer", auth_source=AUTH_SOURCE_LDAP,
            external_id=duser.sid,
        )
        db.add(user)
    else:
        if clash is None or str(clash.id) == str(user.id):
            user.email = email
        user.username = (duser.display_name or duser.username)[:_MAX_NAME]
    user.external_dn = duser.dn
    user.is_active = not duser.disabled
    if _is_admin(groups, admin_group_dn):
        user.role = "admin"
    elif user.role == "admin":
        user.role = "viewer"
    db.flush()
    return user


def provision_login(
    db: Session, duser: DirectoryUser, groups: list[DirectoryGroup], admin_group_dn: str
) -> User:
    """AD 인증에 성공한 사용자를 만들거나 갱신하고 AD 그룹 구성원을 맞춘다."""
    user = _upsert_user(db, duser, groups, admin_group_dn)
    rows = _upsert_groups(db, groups)
    _set_directory_memberships(db, user, [rows[g.sid] for g in groups])
    return user


def _create_newcomers(db: Session, newcomers: list[DirectoryUser], memberships: dict, rows: dict,
                      admin_group_dn: str, counts: dict) -> None:
    """아직 로그인하지 않은 AD 사용자를 미리 만든다. 같은 이메일의 로컬 계정이 있으면 건너뛰고 알린다."""
    for duser in newcomers:
        groups = memberships[duser.sid]
        try:
            with db.begin_nested():
                user = _upsert_user(db, duser, groups, admin_group_dn)
                _set_directory_memberships(db, user, [rows[g.sid] for g in groups])
        except DirectoryConflict:
            if len(counts["conflicts"]) < _MAX_REPORTED:
                counts["conflicts"].append(_email_for(duser))
            continue
        counts["created"] += 1


# 한 번에 이만큼 넘게 비활성화하려 들면 AD 검색 범위나 연결이 잘못됐을 가능성이 더 크다
MASS_DEACTIVATION_MIN = 5
MASS_DEACTIVATION_RATIO = 0.5


def _refuse_mass_deactivation(db_users: list[User], by_sid: dict) -> None:
    active = [u for u in db_users if u.is_active]
    leaving = [u for u in active if (by_sid.get(u.external_id) is None or by_sid[u.external_id].disabled)]
    if len(leaving) >= MASS_DEACTIVATION_MIN and len(leaving) > len(active) * MASS_DEACTIVATION_RATIO:
        raise DirectoryUnavailable(
            f"refusing to deactivate {len(leaving)} of {len(active)} active directory users in one sync"
        )


def sync_directory(db: Session, client: DirectoryClient, admin_group_dn: str, *, preprovision: bool = True) -> dict:
    """AD 상태에 맞춰 그룹과 사용자를 정리한다. AD에서 먼저 모두 읽고 나서 쓴다.

    AD에 연결하지 못하면 아무것도 바꾸지 않고 DirectoryUnavailable을 그대로 던진다.
    AD가 사용자를 한 명도 돌려주지 않으면 설정 오류로 보고 멈춘다(전원 비활성화 방지).
    """
    ad_users = client.list_users()
    ad_groups = client.list_groups()
    db_users = list(db.scalars(
        select(User).where(User.auth_source == AUTH_SOURCE_LDAP, User.external_id.is_not(None))
    ))
    if db_users and not ad_users:
        raise DirectoryUnavailable("directory returned no users; refusing to deactivate everyone")

    by_sid = {u.sid: u for u in ad_users}
    known_sids = {u.external_id for u in db_users}
    newcomers = [u for u in ad_users if not u.disabled and u.sid not in known_sids] if preprovision else []
    memberships: dict[str, list[DirectoryGroup]] = {}
    for user in db_users:
        duser = by_sid.get(user.external_id)
        if duser is not None and not duser.disabled:
            memberships[user.external_id] = client.user_groups(duser.dn)
    for duser in newcomers:
        memberships[duser.sid] = client.user_groups(duser.dn)

    _refuse_mass_deactivation(db_users, by_sid)
    counts = {"users_checked": len(db_users), "deactivated": 0, "updated": 0, "groups_removed": 0,
              "created": 0, "conflicts": [], "recreated_groups": []}
    known = list(ad_groups) + [g for gs in memberships.values() for g in gs]
    live_dns = {normalize_dn(g.dn) for g in known}
    rows = _upsert_groups(db, known)

    live_sids = {g.sid for g in known}
    for group in list(db.scalars(select(UserGroup).where(UserGroup.source == GROUP_SOURCE_LDAP))):
        if group.external_id not in live_sids:
            # 문서 ACL 항목은 남는다(fail-closed). 아무에게도 매칭되지 않는다.
            if group.external_dn and normalize_dn(group.external_dn) in live_dns:
                counts["recreated_groups"].append(group.name)
            db.delete(group)
            counts["groups_removed"] += 1
    db.flush()
    _create_newcomers(db, newcomers, memberships, rows, admin_group_dn, counts)

    for user in db_users:
        duser = by_sid.get(user.external_id)
        if duser is None or duser.disabled:
            if user.is_active:
                user.is_active = False
                counts["deactivated"] += 1
            continue
        groups = memberships[user.external_id]
        _upsert_user(db, duser, groups, admin_group_dn)
        _set_directory_memberships(db, user, [rows[g.sid] for g in groups])
        counts["updated"] += 1
    db.flush()
    return counts
