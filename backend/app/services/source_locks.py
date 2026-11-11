"""원천이 기준인 대상의 수동 수정 차단(v3 마일스톤 3).

커넥터로 들어온 문서의 ACL·등급, AD에서 동기화된 그룹의 이름·구성원은 다음 동기화가 덮어쓴다.
화면에서 고치면 잠시 다른 권한이 적용되다가 되돌아가므로, 처음부터 409로 막고 어디서 바꿔야
하는지 알려 준다. AD 계정의 비밀번호와 커넥터용 시스템 계정도 여기서 막는다.
"""
from fastapi import HTTPException
from sqlalchemy import exists, select

from app.db.models.source_connector import SourceItem
from app.db.models.user import AUTH_SOURCE_LDAP, AUTH_SOURCE_LOCAL, AUTH_SOURCE_SYSTEM, User
from app.db.models.user_group import GROUP_SOURCE_LOCAL, UserGroup

CONNECTOR_DOCUMENT_DETAIL = "파일 서버에서 가져온 문서입니다. 접근 권한과 보안등급은 파일 서버와 원천 연결 설정에서 바꾸세요."
DIRECTORY_GROUP_DETAIL = "AD에서 동기화되는 그룹입니다. 이름과 구성원은 AD에서 바꾸세요."
DIRECTORY_PASSWORD_DETAIL = "사내 계정(AD)의 비밀번호는 AD에서 바꾸세요."
DIRECTORY_ACCOUNT_DETAIL = (
    "사내 계정(AD)의 사용 여부와 관리자 권한은 AD에서 정합니다. 계정 사용 중지는 AD에서, "
    "관리자 지정은 관리자 그룹(LDAP_ADMIN_GROUP_DN) 구성원으로 바꾸세요."
)
SYSTEM_ACCOUNT_DETAIL = "원천 연결용 시스템 계정은 바꾸거나 지울 수 없습니다."


async def is_connector_document(db, document_id) -> bool:
    return bool(await db.scalar(select(exists().where(SourceItem.document_id == document_id))))


async def ensure_not_connector_document(db, document_id) -> None:
    if await is_connector_document(db, document_id):
        raise HTTPException(status_code=409, detail=CONNECTOR_DOCUMENT_DETAIL)


def ensure_local_group(group: UserGroup) -> None:
    if (group.source or GROUP_SOURCE_LOCAL) != GROUP_SOURCE_LOCAL:
        raise HTTPException(status_code=409, detail=DIRECTORY_GROUP_DETAIL)


def ensure_local_password(user: User) -> None:
    if (user.auth_source or AUTH_SOURCE_LOCAL) != AUTH_SOURCE_LOCAL:
        raise HTTPException(status_code=409, detail=DIRECTORY_PASSWORD_DETAIL)


def ensure_directory_fields_unchanged(user: User, *, role: str | None, is_active: bool | None) -> None:
    """AD 계정의 사용 여부와 관리자 여부는 다음 디렉터리 동기화가 덮어쓴다. 되돌아갈 변경은 처음부터 막는다."""
    if user.auth_source != AUTH_SOURCE_LDAP:
        return
    changes_active = is_active is not None and is_active != user.is_active
    changes_admin = role is not None and (role == "admin") != (user.role == "admin")
    if changes_active or changes_admin:
        raise HTTPException(status_code=409, detail=DIRECTORY_ACCOUNT_DETAIL)


def ensure_not_system_account(user: User) -> None:
    if user.auth_source == AUTH_SOURCE_SYSTEM:
        raise HTTPException(status_code=403, detail=SYSTEM_ACCOUNT_DETAIL)
