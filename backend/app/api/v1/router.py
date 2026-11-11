from fastapi import APIRouter

from app.api.v1.endpoints import access_tokens, admin, answer_traces, auth, connectors, chat, cleaning_rules, collections, dictionary, documents, golden_queries, governance, groups, projects, search, stats, users, workflows

from app.mcp import server as mcp_server

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(admin.router, tags=["admin"])
api_router.include_router(answer_traces.router, tags=["admin"])
api_router.include_router(governance.router, tags=["admin"])
api_router.include_router(connectors.router, tags=["admin"])
api_router.include_router(access_tokens.router, tags=["access-tokens"])
api_router.include_router(mcp_server.router, tags=["mcp"])
api_router.include_router(dictionary.router, tags=["admin"])
api_router.include_router(cleaning_rules.router, tags=["admin"])
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
api_router.include_router(groups.router, prefix="/groups", tags=["groups"])
api_router.include_router(chat.router, tags=["chat"])
api_router.include_router(workflows.router, prefix="/workflows", tags=["workflows"])
