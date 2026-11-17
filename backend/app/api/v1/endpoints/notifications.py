"""화면 알림 API(전체 점검 2-7, 2026-11-16). 로그인한 사람은 자기 알림만 읽고 지운다."""
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user
from app.db.models.notification import Notification
from app.db.models.user import User
from app.db.session import get_db

router = APIRouter()


class NotificationOut(BaseModel):
    id: str
    kind: str
    title: str
    body: str | None
    link: str | None
    created_at: datetime
    read_at: datetime | None


class NotificationList(BaseModel):
    items: list[NotificationOut]
    unread_count: int


def _out(row: Notification) -> NotificationOut:
    return NotificationOut(
        id=str(row.id), kind=row.kind, title=row.title, body=row.body, link=row.link,
        created_at=row.created_at, read_at=row.read_at,
    )


@router.get("/notifications", response_model=NotificationList)
async def list_notifications(
    unread_only: bool = False,
    limit: int = Query(30, gt=0, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    mine = Notification.user_id == current_user.id
    stmt = select(Notification).where(mine)
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    rows = (await db.scalars(stmt.order_by(Notification.created_at.desc()).limit(limit))).all()
    unread = await db.scalar(
        select(func.count()).select_from(Notification).where(mine, Notification.read_at.is_(None))
    )
    return NotificationList(items=[_out(row) for row in rows], unread_count=unread or 0)


@router.post("/notifications/read-all")
async def mark_all_read(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        update(Notification)
        .where(Notification.user_id == current_user.id, Notification.read_at.is_(None))
        .values(read_at=datetime.utcnow())
    )
    await db.commit()
    return {"updated": result.rowcount}


@router.post("/notifications/{notification_id}/read", response_model=NotificationOut)
async def mark_read(
    notification_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = await db.get(Notification, notification_id)
    # 남의 알림은 있는지조차 알려 주지 않는다
    if row is None or str(row.user_id) != str(current_user.id):
        raise HTTPException(status_code=404, detail="알림을 찾을 수 없습니다")
    if row.read_at is None:
        row.read_at = datetime.utcnow()
        await db.commit()
        await db.refresh(row)
    return _out(row)


@router.delete("/notifications/{notification_id}", status_code=204)
async def delete_notification(
    notification_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        delete(Notification).where(Notification.id == notification_id, Notification.user_id == current_user.id)
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="알림을 찾을 수 없습니다")
    await db.commit()
