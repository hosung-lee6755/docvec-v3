"""AD가 없는 회사의 계정 관리: 관리자 계정 발급, 비밀번호 초기화, CSV 일괄 등록.

발급하거나 초기화한 비밀번호는 임시 비밀번호다. 사용자는 첫 로그인 뒤 바꿔야 다른 기능을 쓸 수 있다
(deps.get_current_user). 초기화하면 세션 버전을 올려 기존 로그인을 끊고, 외부 에이전트 토큰도 회수한다.
일괄 등록은 모든 행을 먼저 확인하고, 한 행이라도 문제가 있으면 아무 계정도 만들지 않는다.
"""
from __future__ import annotations

import csv
import io
import re
import secrets
import string
from dataclasses import dataclass, field
from datetime import datetime
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_password_hash
from app.db.models.access_token import PersonalAccessToken
from app.db.models.user import AUTH_SOURCE_LDAP, AUTH_SOURCE_LOCAL, User
from app.db.models.user_group import UserGroup, UserGroupMember
from app.services.audit import log_audit

TEMP_PASSWORD_LENGTH = 14
MAX_IMPORT_ROWS = 500
ROLES = ("viewer", "editor", "admin")
CLEARANCE_LEVELS = ("Public", "Internal", "Confidential")
GROUP_SOURCE_LOCAL = "local"
_EMAIL = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")
# 영문과 한국어 머리글을 모두 받는다. 엑셀에서 한국어 머리글로 만든 파일도 그대로 올릴 수 있게 한다.
_HEADER_ALIASES = {
    "email": "email", "이메일": "email", "메일": "email",
    "username": "username", "name": "username", "이름": "username", "사용자명": "username",
    "role": "role", "역할": "role",
    "clearance_level": "clearance_level", "clearance": "clearance_level", "열람등급": "clearance_level",
    "groups": "groups", "group": "groups", "그룹": "groups",
}
_GROUP_SEPARATOR = re.compile(r"[;|]")
_PASSWORD_ALPHABET = string.ascii_letters + string.digits


class AccountError(ValueError):
    """계정을 만들거나 초기화할 수 없다. 메시지는 화면에 그대로 보인다."""


@dataclass(frozen=True)
class ImportRow:
    line: int
    email: str
    username: str
    role: str
    clearance_level: str | None
    groups: tuple[str, ...]


@dataclass(frozen=True)
class ImportProblem:
    line: int
    message: str


@dataclass
class AccountImportError(Exception):
    problems: list[ImportProblem] = field(default_factory=list)


def generate_temporary_password() -> str:
    """영문 대소문자와 숫자를 섞은 임시 비밀번호. 숫자와 문자가 모두 들어가게 한다."""
    while True:
        candidate = "".join(secrets.choice(_PASSWORD_ALPHABET) for _ in range(TEMP_PASSWORD_LENGTH))
        if any(c.isdigit() for c in candidate) and any(c.isalpha() for c in candidate):
            return candidate


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


async def _email_taken(db: AsyncSession, email: str) -> bool:
    return await db.scalar(select(User.id).where(func.lower(User.email) == email)) is not None


async def create_local_account(
    db: AsyncSession, *, email: str, username: str, actor: User,
    role: str = "viewer", clearance_level: str | None = None,
) -> tuple[User, str]:
    """로컬 계정을 만들고 (계정, 임시 비밀번호)를 돌려준다. 커밋은 호출자가 한다."""
    email = normalize_email(email)
    if not _EMAIL.match(email):
        raise AccountError(f"이메일 형식이 올바르지 않습니다: {email}")
    if role not in ROLES:
        raise AccountError(f"역할은 {', '.join(ROLES)} 중 하나여야 합니다.")
    if clearance_level is not None and clearance_level not in CLEARANCE_LEVELS:
        raise AccountError(f"열람등급은 {', '.join(CLEARANCE_LEVELS)} 중 하나여야 합니다.")
    if await _email_taken(db, email):
        raise AccountError(f"이미 쓰는 이메일입니다: {email}")

    temporary = generate_temporary_password()
    user = User(
        id=uuid4(), email=email, username=(username or "").strip() or email.split("@")[0],
        hashed_password=get_password_hash(temporary), role=role, is_active=True,
        auth_source=AUTH_SOURCE_LOCAL, must_change_password=True, token_version=0,
    )
    if clearance_level:
        user.clearance_level = clearance_level
    db.add(user)
    await db.flush()
    log_audit(db, str(actor.id), "user.create", "user", str(user.id),
              detail={"email": email, "role": role, "clearance_level": user.clearance_level})
    return user, temporary


async def reset_local_password(db: AsyncSession, user: User, *, actor: User) -> str:
    """임시 비밀번호를 새로 발급한다. 기존 로그인은 끊기고 외부 에이전트 토큰은 회수된다.
    비밀번호가 새어 초기화하는 경우가 많아, 그 비밀번호로 만든 토큰이 계속 쓰이지 않게 한다."""
    if user.auth_source != AUTH_SOURCE_LOCAL:
        raise AccountError("AD 계정의 비밀번호는 AD에서 바꿉니다. 이 화면에서는 로컬 계정만 초기화할 수 있습니다.")
    temporary = generate_temporary_password()
    user.hashed_password = get_password_hash(temporary)
    user.must_change_password = True
    revoked = await _end_sessions_and_tokens(db, user, actor)
    log_audit(db, str(actor.id), "user.password_reset", "user", str(user.id),
              detail={"revoked_agent_tokens": revoked})
    return temporary


async def _end_sessions_and_tokens(db: AsyncSession, user: User, actor: User) -> int:
    """기존 로그인을 끊고(세션 버전 올림) 외부 에이전트 토큰을 회수한다. 회수한 토큰 수를 돌려준다."""
    user.token_version = int(user.token_version or 0) + 1
    revoked = await db.execute(
        update(PersonalAccessToken)
        .where(PersonalAccessToken.user_id == user.id, PersonalAccessToken.revoked_at.is_(None))
        .values(revoked_at=datetime.utcnow(), revoked_by=actor.id)
    )
    await db.flush()
    return revoked.rowcount or 0


# 해시 형식이 아니므로 어떤 비밀번호도 맞지 않는다(provisioning.UNUSABLE_PASSWORD와 같은 값)
_DIRECTORY_PASSWORD = "!directory-account"


async def link_to_directory(db: AsyncSession, user: User, *, actor: User) -> None:
    """로컬 계정을 AD 계정으로 전환한다. 같은 이메일의 AD 사용자가 처음 로그인하거나 다음 동기화 때
    이 계정을 이어받아, 그동안의 문서·공유·대화가 그대로 남는다. 로컬 비밀번호는 더 쓸 수 없다."""
    if user.auth_source != AUTH_SOURCE_LOCAL:
        raise AccountError("로컬 계정만 AD 계정으로 전환할 수 있습니다.")
    if str(user.id) == str(actor.id):
        raise AccountError("자기 계정은 전환할 수 없습니다. 다른 관리자에게 요청하세요.")
    user.auth_source = AUTH_SOURCE_LDAP
    user.external_id = None
    user.hashed_password = _DIRECTORY_PASSWORD
    user.must_change_password = False
    revoked = await _end_sessions_and_tokens(db, user, actor)
    log_audit(db, str(actor.id), "user.link_directory", "user", str(user.id),
              detail={"email": user.email, "revoked_agent_tokens": revoked})


def _decode(content: bytes) -> str | None:
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None


def _row_problems(email: str, role: str, clearance: str | None, seen: set[str]) -> list[str]:
    problems = []
    if not email:
        problems.append("이메일이 비어 있습니다.")
    elif not _EMAIL.match(email):
        problems.append(f"이메일 형식이 올바르지 않습니다: {email}")
    elif email in seen:
        problems.append(f"파일 안에서 이메일이 중복됩니다: {email}")
    if role not in ROLES:
        problems.append(f"역할은 {', '.join(ROLES)} 중 하나여야 합니다: {role}")
    if clearance is not None and clearance not in CLEARANCE_LEVELS:
        problems.append(f"열람등급은 {', '.join(CLEARANCE_LEVELS)} 중 하나여야 합니다: {clearance}")
    return problems


def _column(name: str | None) -> str | None:
    key = (name or "").strip()
    return _HEADER_ALIASES.get(key.lower()) or _HEADER_ALIASES.get(key)


def parse_user_csv(content: bytes) -> tuple[list[ImportRow], list[ImportProblem]]:
    """CSV를 행으로 바꾼다. 줄 번호는 머리글을 1로 센다. 열은 email(필수), username, role, clearance_level,
    groups(세미콜론이나 |로 구분)이며 한국어 머리글(이메일, 이름, 역할, 열람등급, 그룹)도 받는다."""
    text = _decode(content)
    if text is None:
        return [], [ImportProblem(1, "파일을 UTF-8로 읽을 수 없습니다. 엑셀에서 'CSV UTF-8' 형식으로 저장해 올리세요.")]
    reader = csv.reader(io.StringIO(text))
    columns = [_column(h) for h in next(reader, None) or []]
    if "email" not in columns:
        return [], [ImportProblem(1, "머리글에 email(또는 이메일) 열이 없습니다.")]

    rows: list[ImportRow] = []
    problems: list[ImportProblem] = []
    seen: set[str] = set()
    for line, values in enumerate(reader, start=2):
        if not any((v or "").strip() for v in values):
            continue
        record = {col: (values[i].strip() if i < len(values) else "") for i, col in enumerate(columns) if col}
        email = normalize_email(record.get("email", ""))
        role = record.get("role") or "viewer"
        clearance = record.get("clearance_level") or None
        row_problems = _row_problems(email, role, clearance, seen)
        if row_problems:
            problems.extend(ImportProblem(line, p) for p in row_problems)
            continue
        seen.add(email)
        groups = tuple(g.strip() for g in _GROUP_SEPARATOR.split(record.get("groups", "")) if g.strip())
        rows.append(ImportRow(line, email, record.get("username", ""), role, clearance, groups))
    if len(rows) + len({p.line for p in problems}) > MAX_IMPORT_ROWS:
        return [], [ImportProblem(1, f"한 번에 {MAX_IMPORT_ROWS}명까지 등록할 수 있습니다. 파일을 나눠 올리세요.")]
    return rows, problems


async def _import_problems(
    db: AsyncSession, rows: list[ImportRow],
) -> tuple[list[ImportProblem], dict[str, UserGroup]]:
    """DB와 맞춰 봐야 아는 문제(이미 있는 이메일, 없는 그룹, AD 그룹)를 모은다."""
    emails = [r.email for r in rows]
    taken = set((await db.scalars(
        select(func.lower(User.email)).where(func.lower(User.email).in_(emails)))).all()) if emails else set()
    names = sorted({g for r in rows for g in r.groups})
    groups = {
        g.name: g for g in (await db.scalars(select(UserGroup).where(UserGroup.name.in_(names)))).all()
    } if names else {}
    problems = []
    for row in rows:
        if row.email in taken:
            problems.append(ImportProblem(row.line, f"이미 쓰는 이메일입니다: {row.email}"))
        for name in row.groups:
            group = groups.get(name)
            if group is None:
                problems.append(ImportProblem(row.line, f"없는 그룹입니다: {name}. 그룹 화면에서 먼저 만드세요."))
            elif group.source != GROUP_SOURCE_LOCAL:
                problems.append(ImportProblem(row.line, f"AD에서 가져온 그룹에는 넣을 수 없습니다: {name}"))
    return problems, groups


async def import_local_accounts(db: AsyncSession, rows: list[ImportRow], *, actor: User) -> list[tuple[User, str]]:
    """모든 행을 확인한 뒤 계정을 만들고 그룹에 넣는다. 문제가 있으면 AccountImportError를 던지고 아무것도 만들지 않는다."""
    problems, groups = await _import_problems(db, rows)
    if problems:
        raise AccountImportError(sorted(problems, key=lambda p: p.line))
    created: list[tuple[User, str]] = []
    for row in rows:
        user, temporary = await create_local_account(
            db, email=row.email, username=row.username, role=row.role,
            clearance_level=row.clearance_level, actor=actor,
        )
        for name in row.groups:
            db.add(UserGroupMember(group_id=groups[name].id, user_id=user.id, added_by=str(actor.id)))
        created.append((user, temporary))
    await db.flush()
    log_audit(db, str(actor.id), "user.import", "user", None, detail={"count": len(created)})
    return created
