import pytest
from app.core.security import (
    get_password_hash,
    verify_password,
    create_access_token,
    verify_token,
)

def test_password_hash_and_verify():
    password = "securepassword123"
    hashed = get_password_hash(password)
    assert hashed != password
    assert verify_password(password, hashed)

def test_wrong_password_fails():
    hashed = get_password_hash("correct")
    assert not verify_password("wrong", hashed)

def test_create_and_verify_access_token():
    token = create_access_token({"sub": "user-id-123", "email": "test@test.com"})
    payload = verify_token(token)
    assert payload is not None
    assert payload["sub"] == "user-id-123"

def test_invalid_token_returns_none():
    result = verify_token("not-a-real-token")
    assert result is None
