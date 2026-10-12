"""관리자 엔드포인트(감사 로그·LLM 사용량)와 정제 규칙 엔드포인트 테스트 — 실제 Postgres(SAVEPOINT 롤백).

대상: app/api/v1/endpoints/admin.py, cleaning_rules.py (기존 test_admin_endpoints.py는 403 분기만 다룬다).
"""
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select

from app.api.v1.endpoints import admin as admin_api
from app.api.v1.endpoints import cleaning_rules as rules_api
from app.db.models.audit_log import AuditLog
from app.db.models.cleaning_rule import CleaningRule
from app.db.models.llm_usage_log import LLMUsageLog
from app.schemas.cleaning_rule import CleaningRuleCreate, CleaningRuleUpdate
from tests.unit.api_pg_helpers import (  # noqa: F401
    db_session,
    make_project,
    make_user,
)

T0 = datetime(2026, 5, 1, 12, 0, 0)


async def _expect(status: int, coro):
    with pytest.raises(HTTPException) as exc:
        await coro
    assert exc.value.status_code == status


@pytest.fixture
async def world(db_session):
    admin = await make_user(db_session, "admin", "root")
    viewer = await make_user(db_session, "viewer", "viewer")
    return dict(db=db_session, admin=admin, viewer=viewer)


def _audit(user, action, resource_type, at, **fields) -> AuditLog:
    return AuditLog(user_id=str(user.id), action=action, resource_type=resource_type,
                    created_at=at, **fields)


# ---------- audit logs ----------

@pytest.mark.asyncio
async def test_list_audit_logs_filters_and_orders_newest_first(world):
    db, admin, viewer = world["db"], world["admin"], world["viewer"]
    db.add_all([
        _audit(admin, "user.update", "user", T0, resource_id="r1", detail={"a": 1}, ip_address="1.2.3.4"),
        _audit(admin, "project.member_invite", "project", T0 + timedelta(days=1)),
        _audit(viewer, "user.update", "user", T0 + timedelta(days=2)),
    ])
    await db.flush()

    async def call(**kw):
        params = dict(user_id=None, action=None, resource_type=None, from_date=None, to_date=None,
                      limit=50, offset=0, db=db, current_user=admin)
        params.update(kw)
        return await admin_api.list_audit_logs(**params)

    everything = await call()
    assert everything["total"] == 3
    assert [i["action"] for i in everything["items"]] == ["user.update", "project.member_invite", "user.update"]
    oldest = everything["items"][-1]
    assert oldest["resource_id"] == "r1" and oldest["detail"] == {"a": 1} and oldest["ip_address"] == "1.2.3.4"
    assert oldest["user_id"] == str(admin.id)

    assert (await call(action="user.update"))["total"] == 2
    assert (await call(resource_type="project"))["total"] == 1
    assert (await call(user_id=viewer.id))["total"] == 1
    assert (await call(from_date=T0 + timedelta(hours=1)))["total"] == 2
    assert (await call(to_date=T0 + timedelta(hours=1)))["total"] == 1


@pytest.mark.asyncio
async def test_list_audit_logs_paginates_with_limit_and_offset(world):
    db, admin = world["db"], world["admin"]
    db.add_all([_audit(admin, f"act.{i}", "x", T0 + timedelta(minutes=i)) for i in range(5)])
    await db.flush()

    page = await admin_api.list_audit_logs(None, None, None, None, None, 2, 2, db, admin)

    assert page["total"] == 5
    assert [i["action"] for i in page["items"]] == ["act.2", "act.1"]


# ---------- usage ----------

def _usage(user, provider, model, tin, tout, cost, project=None, at=T0) -> LLMUsageLog:
    return LLMUsageLog(user_id=str(user.id), project_id=str(project.id) if project else None,
                       provider=provider, model_key=model, input_tokens=tin, output_tokens=tout,
                       estimated_cost_usd=Decimal(cost), created_at=at)


@pytest.mark.asyncio
async def test_usage_summary_aggregates_by_model_and_user_ordered_by_cost(world):
    db, admin, viewer = world["db"], world["admin"], world["viewer"]
    project = await make_project(db, admin)
    db.add_all([
        _usage(admin, "openai", "gpt", 100, 50, "0.10", project),
        _usage(admin, "openai", "gpt", 10, 5, "0.01", project),
        _usage(viewer, "anthropic", "claude", 200, 100, "0.50", None, at=T0 + timedelta(days=5)),
    ])
    await db.flush()

    result = await admin_api.get_usage_summary(None, None, None, db, admin)

    assert result["summary"] == {"total_requests": 3, "total_input_tokens": 310,
                                 "total_output_tokens": 155, "total_cost_usd": pytest.approx(0.61)}
    assert [m["model_key"] for m in result["by_model"]] == ["claude", "gpt"]
    assert result["by_model"][1] == {"provider": "openai", "model_key": "gpt", "requests": 2,
                                     "input_tokens": 110, "output_tokens": 55, "cost_usd": pytest.approx(0.11)}
    assert [u["username"] for u in result["by_user"]] == ["viewer", "root"]
    assert result["by_user"][0]["user_id"] == str(viewer.id)


@pytest.mark.asyncio
async def test_usage_summary_applies_project_and_date_filters(world):
    db, admin = world["db"], world["admin"]
    project = await make_project(db, admin)
    db.add_all([
        _usage(admin, "openai", "gpt", 1, 1, "0.1", project, at=T0),
        _usage(admin, "openai", "gpt", 1, 1, "0.2", None, at=T0 + timedelta(days=10)),
    ])
    await db.flush()

    by_project = await admin_api.get_usage_summary(project.id, None, None, db, admin)
    in_range = await admin_api.get_usage_summary(None, T0 + timedelta(days=5), T0 + timedelta(days=20), db, admin)
    empty = await admin_api.get_usage_summary(uuid4(), None, None, db, admin)

    assert by_project["summary"]["total_requests"] == 1
    assert in_range["summary"]["total_cost_usd"] == pytest.approx(0.2)
    assert empty["summary"] == {"total_requests": 0, "total_input_tokens": 0,
                                "total_output_tokens": 0, "total_cost_usd": 0.0}
    assert empty["by_model"] == [] and empty["by_user"] == []


# ---------- cleaning rules ----------

def _rule(admin, name="r", rule_type="EXACT_REMOVE", priority=0, **fields) -> CleaningRule:
    return CleaningRule(id=str(uuid4()), rule_name=name, rule_type=rule_type, pattern="p",
                        priority=priority, created_by=str(admin.id), **fields)


@pytest.mark.asyncio
async def test_create_cleaning_rule_persists_fields_and_defaults(world):
    data = CleaningRuleCreate(rule_name="공백", rule_type="REGEX_REPLACE", pattern=r"\s+", replacement=" ")
    created = await rules_api.create_cleaning_rule(data, world["db"], world["admin"])
    assert (created.rule_name, created.rule_type, created.scope) == ("공백", "REGEX_REPLACE", "PARAGRAPH")
    assert created.enabled is True and created.version == 1 and created.priority == 0
    assert str(created.created_by) == str(world["admin"].id)


def test_cleaning_rule_create_rejects_invalid_regex_and_type():
    with pytest.raises(ValidationError):
        CleaningRuleCreate(rule_name="x", rule_type="REGEX_REPLACE", pattern="(")
    with pytest.raises(ValidationError):
        CleaningRuleCreate(rule_name="x", rule_type="BUILTIN", pattern="a")
    # 정규식 검증은 REGEX_REPLACE에만 적용
    assert CleaningRuleCreate(rule_name="x", rule_type="EXACT_REMOVE", pattern="(").pattern == "("


@pytest.mark.asyncio
async def test_list_cleaning_rules_hides_builtin_and_orders_by_priority(world):
    db, admin = world["db"], world["admin"]
    db.add_all([_rule(admin, "low", priority=1), _rule(admin, "high", priority=9),
                _rule(admin, "builtin", rule_type="BUILTIN", priority=99)])
    await db.flush()

    result = await rules_api.list_cleaning_rules(db, admin)

    assert [r.rule_name for r in result["items"]] == ["high", "low"]


@pytest.mark.asyncio
async def test_update_cleaning_rule_bumps_version_only_when_changed(world):
    db, admin = world["db"], world["admin"]
    rule = _rule(admin)
    db.add(rule)
    await db.flush()
    rid = UUID(str(rule.id))

    unchanged = await rules_api.update_cleaning_rule(rid, CleaningRuleUpdate(), db, admin)
    assert unchanged.version == 1

    changed = await rules_api.update_cleaning_rule(
        rid, CleaningRuleUpdate(rule_name="renamed", enabled=False, priority=5), db, admin)
    assert (changed.rule_name, changed.enabled, changed.priority, changed.version) == ("renamed", False, 5, 2)


@pytest.mark.asyncio
async def test_update_and_delete_cleaning_rule_404_for_builtin_or_missing(world):
    db, admin = world["db"], world["admin"]
    builtin = _rule(admin, rule_type="BUILTIN")
    db.add(builtin)
    await db.flush()

    await _expect(404, rules_api.update_cleaning_rule(UUID(str(builtin.id)), CleaningRuleUpdate(enabled=False), db, admin))
    await _expect(404, rules_api.delete_cleaning_rule(UUID(str(builtin.id)), db, admin))
    await _expect(404, rules_api.update_cleaning_rule(uuid4(), CleaningRuleUpdate(enabled=False), db, admin))
    await _expect(404, rules_api.delete_cleaning_rule(uuid4(), db, admin))


@pytest.mark.asyncio
async def test_delete_cleaning_rule_removes_row(world):
    db, admin = world["db"], world["admin"]
    rule = _rule(admin)
    db.add(rule)
    await db.flush()

    assert await rules_api.delete_cleaning_rule(UUID(str(rule.id)), db, admin) is None
    assert await db.scalar(select(func.count()).select_from(CleaningRule).where(CleaningRule.id == rule.id)) == 0


@pytest.mark.asyncio
async def test_cleaning_rule_endpoints_require_admin(world):
    db, viewer = world["db"], world["viewer"]
    data = CleaningRuleCreate(rule_name="x", rule_type="EXACT_REMOVE", pattern="a")
    await _expect(403, rules_api.list_cleaning_rules(db, viewer))
    await _expect(403, rules_api.create_cleaning_rule(data, db, viewer))
    await _expect(403, rules_api.update_cleaning_rule(uuid4(), CleaningRuleUpdate(), db, viewer))
    await _expect(403, rules_api.delete_cleaning_rule(uuid4(), db, viewer))
