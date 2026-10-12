"""documents/chat 엔드포인트 단위 테스트 공용 헬퍼 (실제 Postgres db_session 기반).

사용자 팩토리, 문서/워크플로우 run 생성기, 404/403 공통 검증 헬퍼를 모은다.
이 모듈은 테스트가 아니라 지원 코드라 pytest가 수집하지 않는다(`_` 접두).
"""
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from tests.unit.test_document_display_run import _run, _version  # noqa: F401
from tests.unit.test_documents_storage_release import OWNER_ID, _doc, db_session  # noqa: F401


def owner_user(role: str = "viewer") -> SimpleNamespace:
    """_doc()이 만드는 문서의 소유자 — check_document_access를 그대로 통과한다."""
    return SimpleNamespace(id=OWNER_ID, role=role, email="owner@example.com")


def admin_user() -> SimpleNamespace:
    return owner_user(role="admin")


def stranger_user() -> SimpleNamespace:
    """문서 소유자도, 컬렉션 멤버도 아닌 사용자."""
    return SimpleNamespace(id=str(uuid4()), role="viewer", email="stranger@example.com")


async def add_doc(db, key: str, **overrides):
    overrides.setdefault("id", uuid4())  # UUID 객체로 — DB가 돌려주는 값과 identity map 키가 일치해야 한다
    doc = _doc(key, **overrides)
    db.add(doc)
    await db.flush()
    return doc


async def doc_with_run(db, key: str, kind: str = "PREPROCESS", **overrides):
    """문서 + 지정 kind 워크플로우 run을 만들고 active_run_id로 지정한다."""
    doc = await add_doc(db, key, **overrides)
    version = await _version(db, kind)
    run = await _run(db, doc, version, "UPLOAD", minutes_ago=1)
    doc.active_run_id = run.id
    await db.flush()
    return doc, run


async def add_step(db, run, block_type: str = "text_clean"):
    """FK(step_id)를 요구하는 산출물(정제 변경/사전 적용)용 실제 블록 인스턴스 + run step."""
    from app.db.models.workflow import WorkflowBlockInstance
    from app.db.models.workflow_run import WorkflowRunStep

    block = WorkflowBlockInstance(id=uuid4(), version_id=run.version_id, block_type=block_type, config={})
    db.add(block)
    await db.flush()
    step = WorkflowRunStep(id=uuid4(), run_id=run.id, block_instance_id=block.id, status="COMPLETED")
    db.add(step)
    await db.flush()
    return step


async def assert_http_error(awaitable, status: int):
    with pytest.raises(HTTPException) as exc_info:
        await awaitable
    assert exc_info.value.status_code == status
    return exc_info.value


async def add_other_user(db):
    """소유자와 다른 실제 User 행(FK 대상) — 다른 사람이 만든 리소스를 시뮬레이션한다."""
    from app.db.models.user import User

    user = User(
        id=str(uuid4()), email=f"{uuid4()}@example.com", username="other",
        hashed_password="!", role="viewer", is_active=True,
    )
    db.add(user)
    await db.flush()
    return user
