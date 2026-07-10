from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user
from app.db.models.audit_log import AuditLog
from app.db.models.llm_usage_log import LLMUsageLog
from app.db.models.user import User
from app.db.session import get_db

router = APIRouter()


def _require_admin(current_user: User) -> None:
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")


@router.get("/admin/audit-logs")
async def list_audit_logs(
    user_id: UUID | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    limit: int = Query(50, gt=0, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)

    filters = []
    if user_id is not None:
        filters.append(AuditLog.user_id == str(user_id))
    if action is not None:
        filters.append(AuditLog.action == action)
    if resource_type is not None:
        filters.append(AuditLog.resource_type == resource_type)
    if from_date is not None:
        filters.append(AuditLog.created_at >= from_date)
    if to_date is not None:
        filters.append(AuditLog.created_at <= to_date)

    total = await db.scalar(select(func.count(AuditLog.id)).where(*filters)) or 0
    rows = (
        await db.scalars(
            select(AuditLog)
            .where(*filters)
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()

    return {
        "total": total,
        "items": [
            {
                "id": str(row.id),
                "user_id": str(row.user_id) if row.user_id else None,
                "action": row.action,
                "resource_type": row.resource_type,
                "resource_id": row.resource_id,
                "detail": row.detail,
                "ip_address": row.ip_address,
                "created_at": row.created_at,
            }
            for row in rows
        ],
    }


@router.get("/admin/usage")
async def get_usage_summary(
    project_id: UUID | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)

    filters = []
    if project_id is not None:
        filters.append(LLMUsageLog.project_id == str(project_id))
    if from_date is not None:
        filters.append(LLMUsageLog.created_at >= from_date)
    if to_date is not None:
        filters.append(LLMUsageLog.created_at <= to_date)

    summary_row = (
        await db.execute(
            select(
                func.count(LLMUsageLog.id),
                func.coalesce(func.sum(LLMUsageLog.input_tokens), 0),
                func.coalesce(func.sum(LLMUsageLog.output_tokens), 0),
                func.coalesce(func.sum(LLMUsageLog.estimated_cost_usd), 0),
            ).where(*filters)
        )
    ).one()
    total_requests, total_input_tokens, total_output_tokens, total_cost_usd = summary_row

    by_model_rows = (
        await db.execute(
            select(
                LLMUsageLog.provider,
                LLMUsageLog.model_key,
                func.count(LLMUsageLog.id),
                func.coalesce(func.sum(LLMUsageLog.input_tokens), 0),
                func.coalesce(func.sum(LLMUsageLog.output_tokens), 0),
                func.coalesce(func.sum(LLMUsageLog.estimated_cost_usd), 0),
            )
            .where(*filters)
            .group_by(LLMUsageLog.provider, LLMUsageLog.model_key)
            .order_by(func.sum(LLMUsageLog.estimated_cost_usd).desc())
        )
    ).all()

    by_user_rows = (
        await db.execute(
            select(
                LLMUsageLog.user_id,
                User.username,
                func.count(LLMUsageLog.id),
                func.coalesce(func.sum(LLMUsageLog.input_tokens), 0),
                func.coalesce(func.sum(LLMUsageLog.output_tokens), 0),
                func.coalesce(func.sum(LLMUsageLog.estimated_cost_usd), 0),
            )
            .join(User, User.id == LLMUsageLog.user_id)
            .where(*filters)
            .group_by(LLMUsageLog.user_id, User.username)
            .order_by(func.sum(LLMUsageLog.estimated_cost_usd).desc())
        )
    ).all()

    return {
        "summary": {
            "total_requests": total_requests,
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "total_cost_usd": float(total_cost_usd),
        },
        "by_model": [
            {
                "provider": provider,
                "model_key": model_key,
                "requests": requests,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost_usd": float(cost_usd),
            }
            for provider, model_key, requests, input_tokens, output_tokens, cost_usd in by_model_rows
        ],
        "by_user": [
            {
                "user_id": str(user_id),
                "username": username,
                "requests": requests,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost_usd": float(cost_usd),
            }
            for user_id, username, requests, input_tokens, output_tokens, cost_usd in by_user_rows
        ],
    }
