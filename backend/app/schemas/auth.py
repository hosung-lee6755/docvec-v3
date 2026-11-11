from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    # 로컬 계정은 이메일, AD 계정은 아이디(sAMAccountName)나 이메일을 받는다(v3 마일스톤 3).
    # 필드 이름은 기존 클라이언트와 맞추려고 email로 둔다.
    email: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: UUID
    email: str
    username: str
    role: str
    is_active: bool
    # v3 마일스톤 3: local, ldap(사내 AD), system(원천 연결용 내부 계정)
    auth_source: str = "local"

    class Config:
        from_attributes = True


class LoginResponse(BaseModel):
    user: UserResponse
    access_token: str
    token_type: str = "bearer"


class UserCreate(BaseModel):
    email: EmailStr
    username: str
    password: str = Field(min_length=8, max_length=128)
    # Optional invite code — if it matches settings.admin_signup_code (and that
    # setting is non-empty), the account is created with role="admin" instead
    # of the default "viewer". See auth.register().
    admin_code: str | None = None
