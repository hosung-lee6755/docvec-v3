from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user, require_admin
from app.db.models.cleaning_rule import CleaningRule
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.cleaning_rule import (
    CleaningRuleCreate,
    CleaningRuleListResponse,
    CleaningRuleResponse,
    CleaningRuleUpdate,
)

router = APIRouter()


@router.get("/admin/cleaning-rules", response_model=CleaningRuleListResponse)
async def list_cleaning_rules(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_admin(current_user)
    rows = (
        await db.scalars(
            select(CleaningRule)
            .where(CleaningRule.rule_type != "BUILTIN")
            .order_by(CleaningRule.priority.desc(), CleaningRule.created_at.desc())
        )
    ).all()
    return {"items": rows}


@router.post("/admin/cleaning-rules", response_model=CleaningRuleResponse)
async def create_cleaning_rule(
    data: CleaningRuleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_admin(current_user)
    rule = CleaningRule(
        id=str(uuid4()),
        rule_name=data.rule_name,
        rule_type=data.rule_type,
        pattern=data.pattern,
        replacement=data.replacement,
        scope=data.scope,
        priority=data.priority,
        enabled=data.enabled,
        created_by=str(current_user.id),
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return rule


@router.patch("/admin/cleaning-rules/{rule_id}", response_model=CleaningRuleResponse)
async def update_cleaning_rule(
    rule_id: UUID,
    data: CleaningRuleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_admin(current_user)
    rule = await db.get(CleaningRule, str(rule_id))
    if not rule or rule.rule_type == "BUILTIN":
        raise HTTPException(status_code=404, detail="정제 규칙을 찾을 수 없습니다")

    updates = data.model_dump(exclude_unset=True)
    for field, field_value in updates.items():
        setattr(rule, field, field_value)
    if updates:
        rule.version += 1

    await db.commit()
    await db.refresh(rule)
    return rule


@router.delete("/admin/cleaning-rules/{rule_id}", status_code=204)
async def delete_cleaning_rule(
    rule_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_admin(current_user)
    rule = await db.get(CleaningRule, str(rule_id))
    if not rule or rule.rule_type == "BUILTIN":
        raise HTTPException(status_code=404, detail="정제 규칙을 찾을 수 없습니다")
    await db.delete(rule)
    await db.commit()
