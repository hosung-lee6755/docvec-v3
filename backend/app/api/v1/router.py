from fastapi import APIRouter

from app.api.v1.endpoints import admin, auth, chat, collections, documents, golden_queries, projects, search, stats, users

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(admin.router, tags=["admin"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(documents.router, prefix="/documents", tags=["documents"])
api_router.include_router(projects.router, prefix="/projects", tags=["projects"])
api_router.include_router(
    collections.router, prefix="/collections", tags=["collections"]
)
api_router.include_router(golden_queries.router, tags=["golden-queries"])
api_router.include_router(search.router, tags=["search"])
api_router.include_router(stats.router, tags=["stats"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(chat.router, tags=["chat"])
