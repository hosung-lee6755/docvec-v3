from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator


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
    # 관리자가 발급하거나 초기화한 임시 비밀번호 상태. 화면은 이 값이 참이면 비밀번호 변경부터 받는다
    must_change_password: bool = False

    @field_validator("must_change_password", mode="before")
    @classmethod
    def _unset_means_false(cls, v):
        # 아직 DB에 쓰기 전인 객체는 기본값이 비어 있다
        return bool(v)

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
