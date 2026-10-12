"""Test security configuration validation."""

import pytest
from pydantic import ValidationError
from app.core.config import Settings


class TestSecurityConfig:
    """Test that config enforces security requirements in production."""

    def test_production_requires_secret_key(self, monkeypatch):
        """Production mode requires SECRET_KEY to be set to a strong value."""
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("SECRET_KEY", "change-me-in-production")

        with pytest.raises(ValidationError, match="SECRET_KEY must be set to a strong random value"):
            Settings()

    def test_production_requires_secret_key_not_empty(self, monkeypatch):
        """Production mode requires SECRET_KEY to be non-empty."""
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("SECRET_KEY", "")

        with pytest.raises(ValidationError, match="SECRET_KEY must be set to a strong random value"):
            Settings()

    def test_production_requires_secret_key_minimum_length(self, monkeypatch):
        """Production mode requires SECRET_KEY to be at least 32 chars."""
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("SECRET_KEY", "short")  # Too short

        with pytest.raises(ValidationError, match="at least 32 characters"):
            Settings()

    def test_production_requires_encryption_key(self, monkeypatch):
        """Production mode requires ENCRYPTION_KEY to be set (no fallback to SECRET_KEY)."""
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("SECRET_KEY", "a" * 32)  # Valid SECRET_KEY
        monkeypatch.setenv("ENCRYPTION_KEY", "")  # Empty ENCRYPTION_KEY

        with pytest.raises(ValidationError, match="ENCRYPTION_KEY must be set in production"):
            Settings()

    def test_development_allows_defaults(self, monkeypatch):
        """Development mode allows default/insecure values."""
        monkeypatch.setenv("ENVIRONMENT", "development")
        monkeypatch.setenv("SECRET_KEY", "change-me-in-production")
        monkeypatch.setenv("ENCRYPTION_KEY", "")

        # Should not raise
        settings = Settings()
        assert settings.is_production is False

    def test_production_with_valid_secrets(self, monkeypatch):
        """Production mode accepts valid secrets."""
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("SECRET_KEY", "a" * 32)  # Valid: 32+ chars
        monkeypatch.setenv("ENCRYPTION_KEY", "b" * 32)  # Required in production

        # Should not raise
        settings = Settings()
        assert settings.is_production is True
        assert settings.secret_key == "a" * 32
        assert settings.encryption_key == "b" * 32
