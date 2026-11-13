"""관리자의 로컬 계정 관리(AD가 없는 회사): 계정 발급, 비밀번호 초기화, CSV 일괄 등록.

임시 비밀번호는 응답에 한 번만 실린다. 저장하지 않으므로 관리자가 그 자리에서 직원에게 전달해야 한다.
AD 로그인을 켠 동안에는 계정을 AD에서 관리하므로 발급과 일괄 등록을 막는다. 같은 이메일의 로컬 계정이
먼저 있으면 그 직원의 AD 로그인이 막히기 때문이다(회원가입을 막는 이유와 같다).
"""
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user, require_admin
from app.core.config import settings
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.access import SecurityLevel
from app.schemas.auth import UserResponse
from app.services import local_accounts as la
from app.services.audit import log_audit

router = APIRouter()

MAX_IMPORT_BYTES = 1_000_000
_DIRECTORY_MANAGED = "사내 계정(AD) 로그인을 쓰는 동안에는 계정을 AD에서 만들고 관리합니다. 이 화면에서는 만들 수 없습니다."


class AccountCreate(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    username: str = Field(default="", max_length=255)
    role: Literal["viewer", "editor", "admin"] = "viewer"
    clearance_level: SecurityLevel | None = None


class IssuedAccount(BaseModel):
    user: UserResponse
    temporary_password: str


class PasswordReset(BaseModel):
    temporary_password: str


class ImportedAccount(BaseModel):
    email: str
    username: str
    role: str
    groups: list[str]
    temporary_password: str


class ImportResult(BaseModel):
    created: list[ImportedAccount]
    count: int


def _ensure_local_accounts_allowed() -> None:
    if settings.ldap_enabled:
        raise HTTPException(status_code=409, detail=_DIRECTORY_MANAGED)


@router.post("", response_model=IssuedAccount, status_code=201)
async def create_account(
    data: AccountCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_admin(current_user)
    _ensure_local_accounts_allowed()
    try:
        user, temporary = await la.create_local_account(
            db, email=data.email, username=data.username, role=data.role,
            clearance_level=data.clearance_level, actor=current_user,
        )
    except la.AccountError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await db.commit()
    await db.refresh(user)
    return IssuedAccount(user=UserResponse.model_validate(user), temporary_password=temporary)


@router.post("/import", response_model=ImportResult, status_code=201)
async def import_accounts(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_admin(current_user)
    _ensure_local_accounts_allowed()
    content = await file.read(MAX_IMPORT_BYTES + 1)
    if len(content) > MAX_IMPORT_BYTES:
        raise HTTPException(status_code=413, detail="파일이 너무 큽니다. 1MB 이하로 나눠 올리세요.")
    rows, problems = la.parse_user_csv(content)
    if not problems and not rows:
        raise HTTPException(status_code=422, detail="등록할 행이 없습니다. 머리글 아래에 직원 정보를 넣으세요.")
    try:
        if problems:
            raise la.AccountImportError(problems)
        created = await la.import_local_accounts(db, rows, actor=current_user)
    except la.AccountImportError as exc:
        # 확인 단계는 DB에 아무것도 쓰지 않으므로 되돌릴 것이 없다
        raise HTTPException(status_code=422, detail={
            "message": "고칠 행이 있어 아무 계정도 만들지 않았습니다. 아래 줄을 고쳐 다시 올리세요.",
            "problems": [{"line": p.line, "message": p.message} for p in exc.problems],
        }) from exc
    await db.commit()
    groups_by_email = {r.email: list(r.groups) for r in rows}
    items = [
        ImportedAccount(email=u.email, username=u.username, role=u.role,
                        groups=groups_by_email.get(u.email, []), temporary_password=temporary)
        for u, temporary in created
    ]
    return ImportResult(created=items, count=len(items))


@router.post("/directory-sync", status_code=202)
async def sync_directory_now(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """주기(LDAP_SYNC_INTERVAL_MINUTES)를 기다리지 않고 AD와 지금 맞춘다. 결과는 감사 로그에 남는다."""
    from app.pipeline.tasks.directory import sync_directory_task

    require_admin(current_user)
    if not settings.ldap_enabled:
        raise HTTPException(status_code=409, detail="사내 계정(AD) 로그인을 쓰지 않아 맞출 대상이 없습니다.")
    log_audit(db, str(current_user.id), "directory.sync_request", "directory", None)
    await db.commit()
    sync_directory_task.delay()
    return {"status": "queued"}


@router.post("/{user_id}/link-directory", response_model=UserResponse)
async def link_directory(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_admin(current_user)
    if not settings.ldap_enabled:
        raise HTTPException(status_code=409, detail="사내 계정(AD) 로그인을 켠 뒤에 전환할 수 있습니다.")
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    try:
        await la.link_to_directory(db, user, actor=current_user)
    except la.AccountError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await db.commit()
    await db.refresh(user)
    return UserResponse.model_validate(user)


@router.post("/{user_id}/reset-password", response_model=PasswordReset)
async def reset_password(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_admin(current_user)
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    try:
        temporary = await la.reset_local_password(db, user, actor=current_user)
    except la.AccountError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await db.commit()
    return PasswordReset(temporary_password=temporary)
