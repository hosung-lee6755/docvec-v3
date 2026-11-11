import pytest
from pydantic import ValidationError
from app.core.config import Settings

def test_default_settings_load(monkeypatch):
    # api/worker containers run with ENVIRONMENT=production set at the OS env
    # level (docker-compose.yml) so the production secret-key guard is
    # exercised even in this dev stack — Settings() picks that up like any
    # other env var, which breaks this test's "true default" assumption
    # unless it's removed first (실측 확인, 2026-08-03).
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    s = Settings()
    assert s.app_name == "DocVec Platform"
    assert s.environment == "development"
    assert s.default_embedding_model == "bge-m3"
    assert s.default_embedding_dimension == 1024

def test_invalid_environment_raises():
    with pytest.raises(ValidationError):
        Settings(environment="invalid_env")

def test_is_production_flag():
    # 프로덕션은 32자 이상 SECRET_KEY와 ENCRYPTION_KEY가 필수다(core/config.py 검증).
    s = Settings(
        environment="production",
        secret_key="k" * 32,
        encryption_key="e" * 32,
        database_url="postgresql+asyncpg://x:x@x/x",
    )
    assert s.is_production is True

def test_qdrant_url_property():
    s = Settings(qdrant_host="qdrant-host", qdrant_port=6333)
    assert s.qdrant_url == "http://qdrant-host:6333"


def _production(**ldap):
    return Settings(
        environment="production", secret_key="k" * 32, encryption_key="e" * 32,
        database_url="postgresql+asyncpg://x:x@x/x", ldap_enabled=True, ldap_url="ldaps://dc:636",
        **{"ldap_bind_dn": "svc@corp", "ldap_bind_password": "pw", "ldap_base_dn": "DC=corp", **ldap},
    )


def test_production_rejects_insecure_ldap():
    # 평문 LDAP 허용과 인증서 검증 끄기는 운영에서 AD 비밀번호 노출로 이어진다
    import pytest

    with pytest.raises(ValueError, match="LDAP_ALLOW_INSECURE"):
        _production(ldap_allow_insecure=True)
    with pytest.raises(ValueError, match="LDAP_TLS_VERIFY"):
        _production(ldap_tls_verify=False)
    assert _production(ldap_ca_cert_file="/certs/ca.pem").ldap_tls_verify is True
    # 빈 바인드 비밀번호는 익명 바인드가 된다
    with pytest.raises(ValueError, match="LDAP_BIND_PASSWORD"):
        _production(ldap_bind_password="")
