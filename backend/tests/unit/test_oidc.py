"""OIDC 로그인(전체 점검 2-6): 흐름, id_token 검증, 계정 연결."""
import json
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from jose import jwk, jwt

from app.api.v1.endpoints import auth
from app.services import oidc
from tests.unit.api_pg_helpers import db_session, make_user  # noqa: F401

ISSUER = "https://sso.example.com/realms/corp"
CLIENT_ID = "docvec"
REDIRECT = "https://docvec.example.com/api/v1/auth/oidc/callback"


def _key_pair() -> tuple[str, dict]:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption(),
    ).decode()
    public = jwk.construct(pem, "RS256").public_key().to_dict()
    return pem, {**public, "kid": "k1", "use": "sig"}


PRIVATE_PEM, PUBLIC_JWK = _key_pair()
OTHER_PEM, _ = _key_pair()


class FakeRedis:
    def __init__(self):
        self.data: dict[str, str] = {}

    def setex(self, key, _ttl, value):
        self.data[key] = value

    def pipeline(self):
        store, calls = self.data, []

        class Pipe:
            def get(self, key):
                calls.append(("get", key))

            def delete(self, key):
                calls.append(("delete", key))

            def execute(self):
                return [store.get(key) if name == "get" else store.pop(key, None) for name, key in calls]

        return Pipe()


@pytest.fixture(autouse=True)
def _oidc_settings(monkeypatch):
    for name, value in {
        "oidc_enabled": True, "oidc_issuer": ISSUER, "oidc_client_id": CLIENT_ID, "oidc_client_secret": "s3cret",
        "oidc_redirect_url": REDIRECT, "oidc_scopes": "openid email profile",
        "oidc_admin_claim": "", "oidc_admin_value": "",
    }.items():
        monkeypatch.setattr(oidc.settings, name, value)


def _token(nonce, pem=PRIVATE_PEM, **overrides) -> str:
    claims = {
        "iss": ISSUER, "aud": CLIENT_ID, "sub": "user-1", "email": "Kim@Example.com", "name": "김철수",
        "exp": int(time.time()) + 300, "iat": int(time.time()), "nonce": nonce,
    }
    claims.update(overrides)
    return jwt.encode(claims, pem, algorithm="RS256", headers={"kid": "k1"})


def _provider(token_for, issuer=ISSUER, seen=None):
    """가짜 로그인 서버. token_for(form)이 토큰 응답의 id_token을 만든다."""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/.well-known/openid-configuration"):
            return httpx.Response(200, json={
                "issuer": issuer, "authorization_endpoint": f"{ISSUER}/auth",
                "token_endpoint": f"{ISSUER}/token", "jwks_uri": f"{ISSUER}/certs",
            })
        if request.url.path.endswith("/certs"):
            return httpx.Response(200, json={"keys": [PUBLIC_JWK]})
        form = {key: values[0] for key, values in parse_qs(request.content.decode()).items()}
        if seen is not None:
            seen.update(form)
        return httpx.Response(200, json={"id_token": token_for(form), "access_token": "at"})

    return httpx.Client(transport=httpx.MockTransport(handler))


def _begin(redis):
    url = oidc.begin_login(redis, _provider(lambda form: ""))
    query = {key: values[0] for key, values in parse_qs(urlparse(url).query).items()}
    return url, query


def test_login_url_carries_state_nonce_and_pkce():
    redis = FakeRedis()

    url, query = _begin(redis)

    assert url.startswith(f"{ISSUER}/auth?")
    assert (query["client_id"], query["redirect_uri"], query["response_type"]) == (CLIENT_ID, REDIRECT, "code")
    saved = json.loads(redis.data[f"oidc_state:{query['state']}"])
    assert query["nonce"] == saved["nonce"] and query["code_challenge_method"] == "S256"
    assert query["code_challenge"] == oidc.pkce_challenge(saved["verifier"])


def test_full_flow_returns_identity_and_sends_the_pkce_verifier():
    redis, seen = FakeRedis(), {}
    _url, query = _begin(redis)
    verifier = json.loads(redis.data[f"oidc_state:{query['state']}"])["verifier"]

    identity = oidc.complete_login(redis, _provider(lambda form: _token(query["nonce"]), seen=seen), query["state"], "abc")

    assert (identity.email, identity.name, identity.is_admin) == ("kim@example.com", "김철수", False)
    assert identity.external_id.startswith("oidc:") and len(identity.external_id) == 69
    assert (seen["code"], seen["code_verifier"], seen["client_secret"]) == ("abc", verifier, "s3cret")


def test_state_can_be_used_only_once():
    redis = FakeRedis()
    _url, query = _begin(redis)
    provider = _provider(lambda form: _token(query["nonce"]))
    oidc.complete_login(redis, provider, query["state"], "abc")

    with pytest.raises(oidc.OidcError, match="state"):
        oidc.complete_login(redis, provider, query["state"], "abc")


@pytest.mark.parametrize("overrides, pem", [
    ({"aud": "another-app"}, PRIVATE_PEM),
    ({"iss": "https://evil.example.com"}, PRIVATE_PEM),
    ({"exp": int(time.time()) - 60}, PRIVATE_PEM),
    ({}, OTHER_PEM),
])
def test_bad_id_token_is_rejected(overrides, pem):
    redis = FakeRedis()
    _url, query = _begin(redis)

    with pytest.raises(oidc.OidcError):
        oidc.complete_login(
            redis, _provider(lambda form: _token(query["nonce"], pem=pem, **overrides)), query["state"], "abc",
        )


def test_wrong_nonce_is_rejected():
    redis = FakeRedis()
    _url, query = _begin(redis)

    with pytest.raises(oidc.OidcError, match="nonce"):
        oidc.complete_login(redis, _provider(lambda form: _token("someone-elses-nonce")), query["state"], "abc")


def test_symmetric_algorithm_is_refused():
    redis = FakeRedis()
    _url, query = _begin(redis)
    forged = jwt.encode({"iss": ISSUER, "aud": CLIENT_ID, "sub": "x"}, "s3cret", algorithm="HS256")

    with pytest.raises(oidc.OidcError, match="algorithm"):
        oidc.complete_login(redis, _provider(lambda form: forged), query["state"], "abc")


def test_discovery_from_another_issuer_is_refused():
    with pytest.raises(oidc.OidcError, match="issuer"):
        oidc.begin_login(FakeRedis(), _provider(lambda form: "", issuer="https://evil.example.com"))


@pytest.mark.parametrize("claims", [
    {"sub": "u", "email": ""},
    {"sub": "", "email": "a@b.com"},
    {"sub": "u", "email": "a@b.com", "email_verified": False},
])
def test_identity_needs_subject_and_a_verified_email(claims):
    with pytest.raises(oidc.OidcError):
        oidc.identity_from(claims)


def test_admin_follows_the_configured_claim(monkeypatch):
    monkeypatch.setattr(oidc.settings, "oidc_admin_claim", "groups")
    monkeypatch.setattr(oidc.settings, "oidc_admin_value", "docvec-admins")
    base = {"sub": "u", "email": "a@b.com"}

    assert oidc.identity_from({**base, "groups": ["staff", "docvec-admins"]}).is_admin
    assert not oidc.identity_from({**base, "groups": ["staff"]}).is_admin
    assert not oidc.identity_from(base).is_admin


def test_exchange_code_is_single_use():
    redis = FakeRedis()
    code = oidc.issue_exchange_code(redis, "user-id")

    assert oidc.redeem_exchange_code(redis, code) == "user-id"
    assert oidc.redeem_exchange_code(redis, code) is None
    assert oidc.redeem_exchange_code(redis, "") is None


def _identity(email="new@example.com", is_admin=False, external_id="oidc:" + "a" * 64):
    return oidc.OidcIdentity(external_id=external_id, email=email, name="새 사용자", is_admin=is_admin)


async def test_first_login_creates_an_oidc_account(db_session):  # noqa: F811
    user = await auth._oidc_user(db_session, _identity())

    assert (user.email, user.role, user.auth_source, user.external_id) == (
        "new@example.com", "viewer", "oidc", "oidc:" + "a" * 64,
    )


async def test_second_login_finds_the_same_account(db_session):  # noqa: F811
    first = await auth._oidc_user(db_session, _identity())

    assert (await auth._oidc_user(db_session, _identity(email="renamed@example.com"))).id == first.id


async def test_existing_account_with_the_same_email_is_not_taken_over(db_session):  # noqa: F811
    local = await make_user(db_session)

    with pytest.raises(oidc.OidcError, match="email_conflict"):
        await auth._oidc_user(db_session, _identity(email=local.email.upper()))


async def test_admin_claim_promotes_and_demotes(db_session, monkeypatch):  # noqa: F811
    monkeypatch.setattr(oidc.settings, "oidc_admin_claim", "groups")
    monkeypatch.setattr(oidc.settings, "oidc_admin_value", "docvec-admins")

    promoted = await auth._oidc_user(db_session, _identity(is_admin=True))
    assert promoted.role == "admin"
    assert (await auth._oidc_user(db_session, _identity(is_admin=False))).role == "viewer"


async def test_exchange_rejects_unknown_code(db_session, monkeypatch):  # noqa: F811
    from unittest.mock import MagicMock

    monkeypatch.setattr(auth, "_oidc_redis", lambda: FakeRedis())
    monkeypatch.setattr(auth, "enforce_rate_limit", lambda *args, **kwargs: None)

    with pytest.raises(HTTPException) as exc_info:
        await auth.oidc_exchange(auth.OidcExchangeRequest(code="nope"), MagicMock(), MagicMock(), db_session)

    assert exc_info.value.status_code == 401


async def test_exchange_returns_a_session_for_the_oidc_user(db_session, monkeypatch):  # noqa: F811
    from unittest.mock import MagicMock

    redis = FakeRedis()
    monkeypatch.setattr(auth, "_oidc_redis", lambda: redis)
    monkeypatch.setattr(auth, "enforce_rate_limit", lambda *args, **kwargs: None)
    user = await auth._oidc_user(db_session, _identity())
    code = oidc.issue_exchange_code(redis, str(user.id))
    response = MagicMock()

    result = await auth.oidc_exchange(auth.OidcExchangeRequest(code=code), response, MagicMock(), db_session)

    assert result.user.email == "new@example.com" and result.access_token
    response.set_cookie.assert_called_once()
