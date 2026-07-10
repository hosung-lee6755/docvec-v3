from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user
from app.db.models.collection import Collection
from app.db.models.document import Document
from app.db.models.user import User
from app.db.session import get_db

router = APIRouter()

_PROCESSING_STATUSES = {"QUEUED", "INGESTING", "PARSING", "CHUNKING", "EMBEDDING", "UPLOADING"}


@router.get("/stats")
async def get_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    total_documents = await db.scalar(
        select(func.count(Document.id)).where(Document.created_by == str(current_user.id))
    ) or 0
    processing = await db.scalar(
        select(func.count(Document.id)).where(
            Document.created_by == str(current_user.id),
            Document.status.in_(_PROCESSING_STATUSES),
        )
    ) or 0
    indexed = await db.scalar(
        select(func.count(Document.id)).where(
            Document.created_by == str(current_user.id),
            Document.status == "INDEXED",
        )
    ) or 0
    collections = await db.scalar(
        select(func.count(Collection.id)).where(Collection.created_by == str(current_user.id))
    ) or 0

    return {
        "total_documents": total_documents,
        "processing": processing,
        "indexed": indexed,
        "collections": collections,
    }
