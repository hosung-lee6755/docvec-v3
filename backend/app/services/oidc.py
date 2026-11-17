"""OIDC 로그인(전체 점검 2-6, 2026-11-16).

사내 통합 로그인(Entra ID, Keycloak, Okta 등)에 인가 코드 흐름과 PKCE로 붙는다. 순서는 이렇다.

1. 화면이 /auth/oidc/login으로 가면, 일회용 state와 nonce, PKCE 검증값을 Redis에 두고 로그인 서버로 보낸다.
2. 로그인 서버가 /auth/oidc/callback으로 code를 돌려주면, state를 한 번만 꺼내 쓰고 code를 토큰으로 바꾼다.
3. id_token의 서명(JWKS), 발급자, 대상(client_id), 만료, nonce를 확인한다.
4. 계정을 찾거나 만든 뒤, 화면에는 60초짜리 일회용 코드만 주소의 # 뒤에 실어 돌려보낸다.
5. 화면이 그 코드를 /auth/oidc/exchange로 바꿔 평소 로그인과 같은 응답을 받는다(토큰이 주소에 남지 않는다).

계정은 발급자와 sub로 묶는다(external_id). 이메일이 같은 로컬 계정이나 AD 계정이 이미 있으면 자동으로
합치지 않고 거절한다. 로그인 서버의 이메일만 믿고 합치면 남의 계정을 차지할 수 있기 때문이다.

SAML은 만들지 않았다. xmlsec 네이티브 라이브러리가 필요해 이미지를 다시 만들어야 하고, 대상 로그인
서버들이 모두 OIDC를 지원한다. 실제 로그인 서버에 붙여 본 것은 아니므로 처음 켤 때 한 번 확인한다.
"""
import base64
import hashlib
import json
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
from jose import JWTError, jwt

from app.core.config import settings

AUTH_SOURCE_OIDC = "oidc"
STATE_TTL_SECONDS = 600
CODE_TTL_SECONDS = 60
HTTP_TIMEOUT_SECONDS = 10
# 대칭키(HS*)와 none은 받지 않는다. 공개 클라이언트 값으로 서명을 위조할 수 있다
ALLOWED_ALGORITHMS = ("RS256", "RS384", "RS512", "ES256", "ES384", "PS256")
_STATE_PREFIX = "oidc_state:"
_CODE_PREFIX = "oidc_code:"


class OidcError(Exception):
    """로그인을 끝낼 수 없다. 메시지는 감사 기록용이고 사용자에게는 일반 문구만 보인다."""


@dataclass(frozen=True)
class OidcIdentity:
    external_id: str
    email: str
    name: str
    is_admin: bool


def is_enabled() -> bool:
    return bool(settings.oidc_enabled and settings.oidc_issuer and settings.oidc_client_id)


def _issuer() -> str:
    return settings.oidc_issuer.rstrip("/")


def discover(client: httpx.Client) -> dict:
    response = client.get(f"{_issuer()}/.well-known/openid-configuration")
    response.raise_for_status()
    config = response.json()
    # 발급자가 다르면 다른 서버의 설정을 읽은 것이다(주소 오타, 중간자)
    if str(config.get("issuer", "")).rstrip("/") != _issuer():
        raise OidcError("discovery issuer mismatch")
    for name in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        if not config.get(name):
            raise OidcError(f"discovery is missing {name}")
    return config


def pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def begin_login(redis_client, client: httpx.Client) -> str:
    """로그인 서버로 보낼 주소를 만든다. state, nonce, PKCE 검증값은 Redis에 잠깐 둔다."""
    config = discover(client)
    state, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(3))
    redis_client.setex(_STATE_PREFIX + state, STATE_TTL_SECONDS, json.dumps({"nonce": nonce, "verifier": verifier}))
    query = urlencode({
        "response_type": "code",
        "client_id": settings.oidc_client_id,
        "redirect_uri": settings.oidc_redirect_url,
        "scope": settings.oidc_scopes,
        "state": state,
        "nonce": nonce,
        "code_challenge": pkce_challenge(verifier),
        "code_challenge_method": "S256",
    })
    return f"{config['authorization_endpoint']}?{query}"


def _take(redis_client, key: str) -> str | None:
    """값을 읽고 바로 지운다(한 번만 쓸 수 있게)."""
    pipeline = redis_client.pipeline()
    pipeline.get(key)
    pipeline.delete(key)
    value = pipeline.execute()[0]
    if value is None:
        return None
    return value.decode("utf-8") if isinstance(value, bytes) else str(value)


def _signing_key(jwks: dict, token: str) -> dict:
    header = jwt.get_unverified_header(token)
    if header.get("alg") not in ALLOWED_ALGORITHMS:
        raise OidcError("id_token algorithm is not allowed")
    keys = jwks.get("keys") or []
    for key in keys:
        if key.get("kid") == header.get("kid"):
            return key
    if len(keys) == 1 and not header.get("kid"):
        return keys[0]
    raise OidcError("id_token signing key not found")


def _is_admin(claims: dict) -> bool:
    claim, wanted = settings.oidc_admin_claim, settings.oidc_admin_value
    if not claim or not wanted:
        return False
    value = claims.get(claim)
    return wanted in value if isinstance(value, list) else value == wanted


def identity_from(claims: dict) -> OidcIdentity:
    subject = str(claims.get("sub") or "")
    email = str(claims.get("email") or "").strip().lower()
    if not subject:
        raise OidcError("id_token has no sub")
    if not email or "@" not in email:
        raise OidcError("id_token has no email")
    # 로그인 서버가 "확인 안 된 이메일"이라고 밝힌 계정은 받지 않는다
    if claims.get("email_verified") is False:
        raise OidcError("email is not verified")
    digest = hashlib.sha256(f"{_issuer()}|{subject}".encode()).hexdigest()
    name = str(claims.get("name") or claims.get("preferred_username") or email.split("@")[0])
    return OidcIdentity(external_id=f"oidc:{digest}", email=email, name=name[:255], is_admin=_is_admin(claims))


def complete_login(redis_client, client: httpx.Client, state: str, code: str) -> OidcIdentity:
    saved = _take(redis_client, _STATE_PREFIX + state) if state else None
    if saved is None:
        raise OidcError("unknown or reused state")
    pending = json.loads(saved)
    config = discover(client)
    response = client.post(config["token_endpoint"], data={
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.oidc_redirect_url,
        "client_id": settings.oidc_client_id,
        "client_secret": settings.oidc_client_secret,
        "code_verifier": pending["verifier"],
    })
    if response.status_code >= 400:
        raise OidcError(f"token endpoint returned {response.status_code}")
    id_token = response.json().get("id_token")
    if not id_token:
        raise OidcError("token response has no id_token")
    jwks_response = client.get(config["jwks_uri"])
    jwks_response.raise_for_status()
    try:
        claims = jwt.decode(
            id_token, _signing_key(jwks_response.json(), id_token), algorithms=list(ALLOWED_ALGORITHMS),
            audience=settings.oidc_client_id, issuer=config["issuer"],
            # access_token을 함께 넘기지 않으므로 at_hash는 비교하지 않는다
            options={"verify_at_hash": False},
        )
    except JWTError as exc:
        raise OidcError(f"id_token rejected: {exc}") from exc
    if not secrets.compare_digest(str(claims.get("nonce") or ""), pending["nonce"]):
        raise OidcError("nonce mismatch")
    return identity_from(claims)


def issue_exchange_code(redis_client, user_id: str) -> str:
    code = secrets.token_urlsafe(32)
    redis_client.setex(_CODE_PREFIX + code, CODE_TTL_SECONDS, user_id)
    return code


def redeem_exchange_code(redis_client, code: str) -> str | None:
    return _take(redis_client, _CODE_PREFIX + code) if code else None


def http_client() -> httpx.Client:
    return httpx.Client(timeout=HTTP_TIMEOUT_SECONDS)
