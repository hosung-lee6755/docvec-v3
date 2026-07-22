from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator, model_validator


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

    # OpenAI (optional)
    openai_api_key: str = ""

    # Encryption key for per-user API keys (Fernet). Falls back to secret_key when
    # unset — set a dedicated value in production so rotating secret_key doesn't
    # also invalidate every stored API key.
    encryption_key: str = ""

    # Invite code required at /auth/register to grant role="admin" instead of
    # the default "viewer". Empty (default) disables admin self-registration
    # entirely — there is no other UI to promote a user to admin.
    admin_signup_code: str = ""

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
        if self.is_production and self.secret_key in self._INSECURE_SECRET_KEYS:
            raise ValueError(
                "SECRET_KEY must be set to a strong random value in production "
                '(e.g. `python -c "import secrets; print(secrets.token_hex(32))"`).'
            )
        return self


settings = Settings()
