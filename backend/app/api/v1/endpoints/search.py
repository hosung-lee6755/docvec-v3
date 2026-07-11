from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user
from app.api.v1.permissions import check_collection_access, check_project_access
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.search import SearchHistoryResponse, SearchRequest, SearchResponse
from app.services.search_service import list_search_history, perform_search

router = APIRouter()


@router.post("/search", response_model=SearchResponse)
async def search(
    request: SearchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if request.project_id:
        await check_project_access(db, request.project_id, current_user, min_role="viewer")
    if request.collection_id:
        await check_collection_access(db, request.collection_id, current_user, min_role="viewer")
    return await perform_search(db, current_user, request)


@router.get("/search/history", response_model=SearchHistoryResponse)
async def search_history(
    limit: int = Query(20, gt=0, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    items = await list_search_history(db, current_user.id, limit=limit)
    return {"items": items}
