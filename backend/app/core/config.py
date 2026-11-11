from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator, model_validator


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # App
    app_name: str = "DocVec Platform"
    environment: str = "development"
    log_level: str = "info"
    debug: bool = False

    # Security
    secret_key: str = "change-me-in-production"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    algorithm: str = "HS256"

    # Database
    database_url: str = "postgresql+asyncpg://docvec:docvec_secret@localhost:5432/docvec"

    # Redis
    redis_url: str = "redis://localhost:6379"

    # Qdrant
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_collection_name: str = "documents"

    # MinIO
    minio_endpoint: str = "localhost:9000"
    minio_public_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minio_secret"
    minio_secure: bool = False
    # presigned URL(브라우저가 직접 접근)을 https로 만들지 여부 — 내부 접속(minio_secure)과 별개.
    # Caddy(https) 뒤에서 MinIO를 같은 출처로 중계할 때 true.
    minio_public_secure: bool = False
    # true 이면 presigned URL 을 호스트 없이 경로+쿼리로 내려준다 — 브라우저가 지금 접속한 출처로 요청하므로
    # 사내 IP/공인 IP/포트와 무관하게 동작한다. Caddy 가 서명 Host(minio_public_endpoint)로 되돌려 보낸다.
    minio_relative_urls: bool = False
    minio_bucket_originals: str = "originals"
    minio_bucket_artifacts: str = "artifacts"

    # Celery
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    # Pipeline defaults
    default_chunk_max_tokens: int = 512
    default_chunk_min_tokens: int = 50
    default_chunk_overlap_tokens: int = 64
    default_embedding_model: str = "bge-m3"
    default_embedding_dimension: int = 1024

    # Upload limits
    max_upload_size_bytes: int = 200 * 1024 * 1024  # 200MB

    # OpenAI (optional)
    openai_api_key: str = ""

    # Encryption key for per-user API keys (Fernet, via PBKDF2). Falls back to secret_key when
    # unset — set a dedicated value in production so rotating secret_key doesn't
    # also invalidate every stored API key. REQUIRED in production (not a fallback).
    encryption_key: str = ""

    # Invite code required at /auth/register to grant role="admin" instead of
    # the default "viewer". Empty (default) disables admin self-registration
    # entirely — there is no other UI to promote a user to admin.
    admin_signup_code: str = ""

    # v3 마일스톤 3: 사내 Active Directory(LDAP) 로그인. 비밀번호는 환경변수로만 받는다.
    # LDAP_URL은 ldaps://host:636 이거나 LDAP_START_TLS=true와 함께 ldap://host:389 를 쓴다.
    ldap_enabled: bool = False
    ldap_url: str = ""
    ldap_start_tls: bool = False
    ldap_tls_verify: bool = True
    ldap_ca_cert_file: str = ""
    ldap_bind_dn: str = ""
    ldap_bind_password: str = ""
    ldap_base_dn: str = ""
    ldap_group_base_dn: str = ""
    # 이 그룹의 구성원은 admin 역할을 받는다(빈 값이면 AD로 관리자를 정하지 않는다).
    ldap_admin_group_dn: str = ""
    ldap_sync_interval_minutes: int = 15
    # 평문 LDAP 허용. 개발용이며 운영(production)에서는 켤 수 없다.
    ldap_allow_insecure: bool = False

    # v3 마일스톤 4 — 외부 에이전트 연동(MCP). 직원이 발급한 개인 접근 토큰으로만 접속한다.
    mcp_enabled: bool = False
    mcp_answer_model: str = "qwen2.5-3b"
    mcp_answer_timeout_seconds: int = 180
    # 심층 검색은 분해, 하위 질문별 검색, 종합을 거쳐 더 오래 걸린다(v3 마일스톤 5)
    mcp_deep_answer_timeout_seconds: int = 300
    # v3 마일스톤 6: 이보다 낮은 OCR 신뢰도의 쪽에서 나온 검색 결과와 인용에 경고를 붙인다(품질 블록 기본값과 같다)
    ocr_low_confidence: float = Field(0.5, ge=0.0, le=1.0)
    mcp_token_default_days: int = 90
    mcp_token_max_days: int = 365
    mcp_tokens_per_user: int = 10

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, v: str) -> str:
        allowed = {"development", "staging", "production", "test"}
        if v not in allowed:
            raise ValueError(f"environment must be one of {allowed}")
        return v

    # Comma-separated list of allowed frontend origins in production (e.g.
    # "https://app.example.com,https://example.com"). Falls back to a
    # deliberately-invalid placeholder so a missing env var fails CORS loudly
    # instead of silently trusting an unrelated domain.
    cors_allowed_origins: str = ""

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def qdrant_url(self) -> str:
        return f"http://{self.qdrant_host}:{self.qdrant_port}"

    _INSECURE_SECRET_KEYS = {"change-me-in-production", ""}

    @model_validator(mode="after")
    def _enforce_production_secret_key(self) -> "Settings":
        if self.is_production:
            # SECRET_KEY: must be strong and random
            if self.secret_key in self._INSECURE_SECRET_KEYS:
                raise ValueError(
                    "SECRET_KEY must be set to a strong random value in production "
                    '(e.g. `python -c "import secrets; print(secrets.token_hex(32))"`).'
                )
            # SECRET_KEY: must be at least 32 chars (256 bits)
            if len(self.secret_key) < 32:
                raise ValueError(
                    "SECRET_KEY must be at least 32 characters (256 bits) in production."
                )
            if self.ldap_enabled:
                # 빈 바인드 DN·비밀번호는 익명 바인드가 되고, 빈 base DN은 엉뚱한 범위를 동기화한다
                missing = [
                    name for name in ("ldap_url", "ldap_bind_dn", "ldap_bind_password", "ldap_base_dn")
                    if not getattr(self, name)
                ]
                if missing:
                    raise ValueError(f"LDAP_ENABLED requires {', '.join(m.upper() for m in missing)}.")
            if self.ldap_enabled and self.ldap_allow_insecure:
                raise ValueError("LDAP_ALLOW_INSECURE cannot be enabled in production.")
            # 인증서 검증을 끄면 중간자가 AD 비밀번호를 그대로 받아 간다
            if self.ldap_enabled and not self.ldap_tls_verify:
                raise ValueError(
                    "LDAP_TLS_VERIFY cannot be disabled in production; set LDAP_CA_CERT_FILE to trust a private CA."
                )
            # ENCRYPTION_KEY: BYOK Fernet key is required (do not fall back to SECRET_KEY)
            if not self.encryption_key:
                raise ValueError(
                    "ENCRYPTION_KEY must be set in production (do not rely on SECRET_KEY fallback). "
                    'Generate with: `python -c "import secrets; print(secrets.token_hex(32))"` '
                    "and pass as Fernet key."
                )
        return self


settings = Settings()
