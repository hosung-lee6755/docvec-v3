"""커넥터 생성에 필요한 부속(v3 마일스톤 3): 시스템 사용자, 원천 클라이언트."""
from __future__ import annotations

from uuid import uuid4

from app.core.crypto import decrypt_secret
from app.db.models.source_connector import SourceConnector
from app.db.models.user import AUTH_SOURCE_SYSTEM, User
from app.services.connectors.smb_client import SmbSourceClient

SYSTEM_EMAIL_DOMAIN = "system.invalid"


def new_service_user(connector_name: str) -> User:
    """커넥터 문서의 업로더 자리를 채우는 내부 계정. 비활성이고 로그인 경로가 없다."""
    return User(
        id=uuid4(),
        email=f"connector-{uuid4().hex}@{SYSTEM_EMAIL_DOMAIN}",
        username=f"[원천] {connector_name}"[:255],
        hashed_password="!system-account",
        role="viewer",
        auth_source=AUTH_SOURCE_SYSTEM,
        is_active=False,
    )


def build_source_client(connector: SourceConnector) -> SmbSourceClient:
    return SmbSourceClient(
        connector.host,
        connector.share,
        connector.username,
        decrypt_secret(connector.password_encrypted),
        port=connector.port or 445,
        base_path=connector.base_path or "",
    )
