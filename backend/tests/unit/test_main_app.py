"""Coverage for app.main — startup lifespan, health/readiness endpoints, CORS
configuration. All infrastructure (DB, Redis, Qdrant, MinIO) is faked."""

import importlib.util
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app import main
from app.core.config import settings

SYSTEM_USER_ID = "00000000-0000-0000-0000-000000000001"


def _session_maker(db):
    @asynccontextmanager
    async def maker():
        yield db

    return maker


def _db(existing_user=None):
    db = MagicMock()
    db.scalar = AsyncMock(return_value=existing_user)
    db.commit = AsyncMock()
    db.execute = AsyncMock()
    return db


# ------------------------------------------------------------------ lifespan


async def _run_lifespan(db, *, storage=None, qdrant=None, refresh=None):
    storage = storage or MagicMock()
    qdrant = qdrant or MagicMock()
    refresh = refresh or AsyncMock()
    with patch("app.services.storage.storage_service", storage), \
         patch("app.services.qdrant_service.qdrant_service", qdrant), \
         patch("app.db.session.async_session_maker", _session_maker(db)), \
         patch("app.core.security.get_password_hash", return_value="HASH"), \
         patch("app.services.dictionary_service.refresh_dictionary_cache", refresh):
        async with main.lifespan(main.app):
            pass
    return storage, qdrant, refresh


async def test_lifespan_initialises_buckets_vector_collection_and_dictionary_cache():
    db = _db(existing_user=object())

    storage, qdrant, refresh = await _run_lifespan(db)

    storage.init_buckets.assert_called_once()
    qdrant.init_collection.assert_called_once_with(
        settings.qdrant_collection_name, settings.default_embedding_dimension
    )
    refresh.assert_awaited_once_with(db)


async def test_lifespan_creates_inactive_system_admin_when_missing():
    db = _db(existing_user=None)

    await _run_lifespan(db)

    user = db.add.call_args.args[0]
    assert str(user.id) == SYSTEM_USER_ID
    assert user.email == "system@docvec.internal"
    assert user.role == "admin"
    assert user.is_active is False  # the system account must never be loginable
    assert user.hashed_password == "HASH"
    db.commit.assert_awaited_once()


async def test_lifespan_does_not_duplicate_existing_system_user():
    db = _db(existing_user=object())

    await _run_lifespan(db)

    db.add.assert_not_called()
    db.commit.assert_not_awaited()


async def test_lifespan_aborts_startup_when_storage_unreachable():
    storage = MagicMock()
    storage.init_buckets.side_effect = ConnectionError("minio down")

    with pytest.raises(ConnectionError):
        await _run_lifespan(_db(), storage=storage)


# ---------------------------------------------------------------- endpoints


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as c:
        yield c


async def test_health_reports_ok_without_touching_dependencies(client):
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def _readiness_patches(*, db_error=None, redis_error=None, qdrant_error=None, minio_error=None):
    db = MagicMock()
    db.execute = AsyncMock(side_effect=db_error)

    redis_client = MagicMock()
    redis_client.ping = AsyncMock(side_effect=redis_error)
    redis_client.aclose = AsyncMock()

    qdrant = MagicMock()
    qdrant._client.get_collections.side_effect = qdrant_error
    storage = MagicMock()
    storage._client.bucket_exists.side_effect = minio_error

    patches = [
        patch("app.db.session.async_session_maker", _session_maker(db)),
        patch("redis.asyncio.from_url", return_value=redis_client),
        patch("app.services.qdrant_service.qdrant_service", qdrant),
        patch("app.services.storage.storage_service", storage),
    ]
    return patches, redis_client, storage


async def _readiness(client, **errors):
    patches, redis_client, storage = _readiness_patches(**errors)
    for p in patches:
        p.start()
    try:
        response = await client.get("/health/ready")
    finally:
        for p in reversed(patches):
            p.stop()
    return response, redis_client, storage


async def test_readiness_ok_when_all_dependencies_respond(client):
    response, redis_client, storage = await _readiness(client)

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "checks": {"database": "ok", "redis": "ok", "qdrant": "ok", "minio": "ok"},
    }
    redis_client.aclose.assert_awaited_once()
    storage._client.bucket_exists.assert_called_once_with(settings.minio_bucket_originals)


@pytest.mark.parametrize(
    "failing,key",
    [
        ({"db_error": RuntimeError("pg down")}, "database"),
        ({"redis_error": ConnectionError("redis down")}, "redis"),
        ({"qdrant_error": RuntimeError("qdrant down")}, "qdrant"),
        ({"minio_error": RuntimeError("minio down")}, "minio"),
    ],
)
async def test_readiness_degrades_with_503_naming_only_the_failed_dependency(client, failing, key):
    response, _r, _s = await _readiness(client, **failing)

    body = response.json()
    assert response.status_code == 503
    assert body["status"] == "degraded"
    assert body["checks"][key] == "error"
    assert [k for k, v in body["checks"].items() if v == "ok"] == [
        k for k in ("database", "redis", "qdrant", "minio") if k != key
    ]


async def test_readiness_does_not_leak_error_details(client):
    response, _r, _s = await _readiness(client, db_error=RuntimeError("password=hunter2"))

    assert "hunter2" not in response.text


async def test_readiness_closes_redis_client_even_when_ping_fails(client):
    _response, redis_client, _s = await _readiness(client, redis_error=ConnectionError("x"))

    redis_client.aclose.assert_awaited_once()


# --------------------------------------------------------------------- CORS


async def test_cors_allows_a_configured_origin_with_credentials(client):
    # 허용 출처는 실행 환경(개발 기본값 또는 CORS_ALLOWED_ORIGINS)이 정한다. 그중 하나로 확인한다.
    origin = main.origins[0]
    response = await client.options(
        "/health",
        headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
    )

    assert response.headers["access-control-allow-origin"] == origin
    assert response.headers["access-control-allow-credentials"] == "true"


async def test_cors_does_not_allow_unknown_origin(client):
    response = await client.options(
        "/health",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )

    assert "access-control-allow-origin" not in response.headers


# ----------------------------------------------------- production bootstrap


def _load_main_as(name: str):
    """Executes app/main.py as a throwaway module so import-time config checks
    run again without replacing the shared `app.main.app` other tests use."""
    spec = importlib.util.spec_from_file_location(name, Path(main.__file__))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_production_refuses_to_start_without_cors_origins():
    with patch.object(type(settings), "is_production", property(lambda _s: True)), \
         patch.object(settings, "cors_allowed_origins", "  ,  "):
        with pytest.raises(RuntimeError, match="CORS_ALLOWED_ORIGINS"):
            _load_main_as("app_main_prod_no_cors")


def test_production_uses_configured_origins_and_hides_docs():
    with patch.object(type(settings), "is_production", property(lambda _s: True)), \
         patch.object(settings, "cors_allowed_origins", "https://a.example, https://b.example"):
        module = _load_main_as("app_main_prod_ok")

    assert module.origins == ["https://a.example", "https://b.example"]
    assert module.app.docs_url is None


def test_development_allows_only_local_origins_and_serves_docs():
    # 컨테이너는 ENVIRONMENT=production으로 돈다. 개발 모드의 기본값은 새로 읽어 확인한다.
    with patch.object(type(settings), "is_production", property(lambda _s: False)):
        module = _load_main_as("app_main_dev")

    assert "http://localhost:3000" in module.origins
    assert all("localhost" in o or "127.0.0.1" in o for o in module.origins)
    assert module.app.docs_url == "/docs"
