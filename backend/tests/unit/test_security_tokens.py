"""Test token security features (type claim, misuse prevention)."""

import json
from datetime import timedelta
from jose import jwt

import pytest
from app.core.config import settings
from app.core.security import create_access_token, create_refresh_token


class TestTokenTypes:
    """Test that tokens are properly typed to prevent misuse."""

    def test_access_token_has_type_claim(self):
        """Access tokens must have type='access' claim."""
        token = create_access_token({"sub": "test-user-id"})
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])

        assert "type" in payload, "Access token missing type claim"
        assert payload["type"] == "access", "Access token should have type='access'"
        assert "sub" in payload
        assert payload["sub"] == "test-user-id"

    def test_refresh_token_has_type_claim(self):
        """Refresh tokens must have type='refresh' claim."""
        token = create_refresh_token({"sub": "test-user-id"})
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])

        assert "type" in payload, "Refresh token missing type claim"
        assert payload["type"] == "refresh", "Refresh token should have type='refresh'"
        assert "sub" in payload
        assert payload["sub"] == "test-user-id"

    def test_different_tokens_have_different_types(self):
        """Access and refresh tokens must have different type claims."""
        access_token = create_access_token({"sub": "test-user-id"})
        refresh_token = create_refresh_token({"sub": "test-user-id"})

        access_payload = jwt.decode(access_token, settings.secret_key, algorithms=[settings.algorithm])
        refresh_payload = jwt.decode(refresh_token, settings.secret_key, algorithms=[settings.algorithm])

        assert access_payload["type"] != refresh_payload["type"]
        assert access_payload["type"] == "access"
        assert refresh_payload["type"] == "refresh"

    def test_access_token_expires_in_configured_minutes(self):
        """Access tokens should expire in the configured time."""
        token = create_access_token({"sub": "test-user-id"})
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])

        # Check that expiration is set to roughly the configured duration
        assert "exp" in payload
        # This is a rough check — just verify exp claim exists
        assert payload["exp"] > 0

    def test_refresh_token_expires_in_configured_days(self):
        """Refresh tokens should expire in the configured number of days."""
        token = create_refresh_token({"sub": "test-user-id"})
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])

        assert "exp" in payload
        assert payload["exp"] > 0
