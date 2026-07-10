import pytest
from pydantic import ValidationError
from app.core.config import Settings

def test_default_settings_load():
    s = Settings()
    assert s.app_name == "DocVec Platform"
    assert s.environment == "development"
    assert s.default_embedding_model == "bge-m3"
    assert s.default_embedding_dimension == 1024

def test_invalid_environment_raises():
    with pytest.raises(ValidationError):
        Settings(environment="invalid_env")

def test_is_production_flag():
    s = Settings(environment="production", secret_key="x", database_url="postgresql+asyncpg://x:x@x/x")
    assert s.is_production is True

def test_qdrant_url_property():
    s = Settings(qdrant_host="qdrant-host", qdrant_port=6333)
    assert s.qdrant_url == "http://qdrant-host:6333"
