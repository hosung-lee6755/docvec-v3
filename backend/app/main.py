import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.logging import configure_logging

configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from sqlalchemy import select

    from app.core.security import get_password_hash
    from app.db.models.user import User
    from app.db.session import async_session_maker
    from app.services.qdrant_service import qdrant_service
    from app.services.storage import storage_service

    storage_service.init_buckets()
    qdrant_service.init_collection(
        settings.qdrant_collection_name,
        settings.default_embedding_dimension,
    )

    system_user_id = "00000000-0000-0000-0000-000000000001"
    async with async_session_maker() as db:
        existing = await db.scalar(select(User).where(User.id == system_user_id))
        if not existing:
            system_user = User(
                id=system_user_id,
                email="system@docvec.internal",
                username="system",
                hashed_password=get_password_hash(""),
                role="admin",
                is_active=False,
            )
            db.add(system_user)
            await db.commit()

    yield


app = FastAPI(
    title="DocVec Platform",
    version="0.1.0",
    docs_url="/docs" if not settings.is_production else None,
    lifespan=lifespan,
)

if settings.is_production:
    origins = ["https://example.com"]
else:
    origins = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/health/ready")
async def readiness():
    """Checks every dependency the API actually needs to serve traffic — plain
    /health only proves the process is alive, which previously was the only
    signal available and would report 'ok' even with Postgres/Redis/Qdrant/MinIO
    unreachable.
    """
    import redis.asyncio as aioredis
    from fastapi.concurrency import run_in_threadpool
    from sqlalchemy import text

    from app.db.session import async_session_maker
    from app.services.qdrant_service import qdrant_service
    from app.services.storage import storage_service

    checks: dict[str, str] = {}

    try:
        async with async_session_maker() as db:
            await db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        logger.exception("readiness check failed", extra={"dependency": "database"})
        checks["database"] = f"error: {exc}"

    try:
        redis_client = aioredis.from_url(settings.redis_url)
        try:
            await redis_client.ping()
        finally:
            await redis_client.aclose()
        checks["redis"] = "ok"
    except Exception as exc:
        logger.exception("readiness check failed", extra={"dependency": "redis"})
        checks["redis"] = f"error: {exc}"

    try:
        await run_in_threadpool(qdrant_service._client.get_collections)
        checks["qdrant"] = "ok"
    except Exception as exc:
        logger.exception("readiness check failed", extra={"dependency": "qdrant"})
        checks["qdrant"] = f"error: {exc}"

    try:
        await run_in_threadpool(
            storage_service._client.bucket_exists, settings.minio_bucket_originals
        )
        checks["minio"] = "ok"
    except Exception as exc:
        logger.exception("readiness check failed", extra={"dependency": "minio"})
        checks["minio"] = f"error: {exc}"

    healthy = all(v == "ok" for v in checks.values())
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={"status": "ok" if healthy else "degraded", "checks": checks},
    )
