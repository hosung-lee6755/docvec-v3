"""전체 라우트 인증 강제 + 컬렉션 권한 매트릭스.

1. 공개 허용목록에 없는 모든 라우트는 토큰 없이 호출하면 401/403이다(새 엔드포인트를 만들고
   인증을 빼먹으면 이 테스트가 실패한다).
2. `check_collection_access`의 역할 매트릭스를 실제 DB로 확인한다.
"""
import re
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute

from app.api.v1.permissions import check_collection_access
from app.db.models.collection import Collection
from app.db.models.collection_member import CollectionMember
from app.db.models.project import Project
from app.db.models.project_member import ProjectMember
from app.db.models.user import User
from app.main import app
from tests.unit.test_documents_storage_release import OWNER_ID, db_session  # noqa: F401

# 인증 없이 호출 가능해야 하는 라우트(메서드, 경로 정규식). 여기에 추가하는 것은 의도적 결정이다.
PUBLIC_ROUTES = {
    ("GET", "/health"),
    ("GET", "/health/ready"),
    ("POST", "/api/v1/auth/register"),
    ("POST", "/api/v1/auth/login"),
    # 로그인 화면이 회원가입 링크를 보일지 정한다. 설정 값 세 개만 돌려준다
    ("GET", "/api/v1/auth/options"),
    ("POST", "/api/v1/auth/refresh"),
    # 리프레시 쿠키만 지운다 — 액세스 토큰이 만료된 사용자도 로그아웃할 수 있어야 한다.
    ("POST", "/api/v1/auth/logout"),
    # MCP 무상태 서버는 GET(서버 발신 스트림)과 DELETE(세션 종료)를 지원하지 않아 항상 405만 돌려준다.
    # 데이터를 내지 않으므로 인증 전에 답해도 된다. 실제 요청(POST)은 개인 접근 토큰을 요구한다.
    ("GET", "/api/v1/mcp"),
    ("DELETE", "/api/v1/mcp"),
}
FRAMEWORK_PATHS = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}


def _concrete_path(path: str) -> str:
    return re.sub(r"\{[^}]+\}", str(uuid4()), path)


def _protected_routes() -> list[tuple[str, str]]:
    routes = []
    for route in app.routes:
        if not isinstance(route, APIRoute) or route.path in FRAMEWORK_PATHS:
            continue
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            if (method, route.path) not in PUBLIC_ROUTES:
                routes.append((method, route.path))
    return routes


def test_there_are_many_protected_routes():
    # 라우트 수집이 깨져 아무것도 검사하지 않는 일을 막는다.
    assert len(_protected_routes()) > 100


@pytest.mark.asyncio
async def test_every_non_public_route_rejects_unauthenticated_requests():
    transport = httpx.ASGITransport(app=app)
    leaked: list[str] = []
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        for method, path in _protected_routes():
            response = await client.request(method, _concrete_path(path))
            if response.status_code not in (401, 403):
                leaked.append(f"{method} {path} -> {response.status_code}")

    assert leaked == [], "인증 없이 접근 가능한 라우트:\n" + "\n".join(leaked)


@pytest.mark.asyncio
async def test_every_non_public_route_rejects_a_garbage_token():
    transport = httpx.ASGITransport(app=app)
    headers = {"Authorization": "Bearer not-a-real-token"}
    leaked: list[str] = []
    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=headers) as client:
        for method, path in _protected_routes():
            response = await client.request(method, _concrete_path(path))
            if response.status_code not in (401, 403):
                leaked.append(f"{method} {path} -> {response.status_code}")

    assert leaked == [], "잘못된 토큰이 통과한 라우트:\n" + "\n".join(leaked)


# ---- 컬렉션 권한 매트릭스 -------------------------------------------------------------------


async def _user(db_session) -> User:
    user = User(
        id=str(uuid4()), email=f"{uuid4()}@example.com", username="u",
        hashed_password="!", role="viewer", is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    return user


async def _collection(db_session, **fields) -> Collection:
    collection = Collection(
        id=uuid4(), name="c", qdrant_collection_name=f"q-{uuid4()}", embedding_model="m",
        chunk_max_tokens=500, chunk_min_tokens=50, chunk_overlap_tokens=0,
        chunk_strategy="fixed", created_by=OWNER_ID, **fields,
    )
    db_session.add(collection)
    await db_session.flush()
    return collection


async def _allowed(db_session, collection, user, min_role) -> bool:
    try:
        await check_collection_access(db_session, collection.id, user, min_role=min_role)
        return True
    except HTTPException as exc:
        assert exc.status_code == 403
        return False


@pytest.mark.asyncio
async def test_personal_collection_roles(db_session):
    collection = await _collection(db_session)
    owner = await db_session.get(User, OWNER_ID)
    viewer, editor, stranger = await _user(db_session), await _user(db_session), await _user(db_session)
    db_session.add_all([
        CollectionMember(collection_id=collection.id, user_id=viewer.id, role="viewer", invited_by=OWNER_ID),
        CollectionMember(collection_id=collection.id, user_id=editor.id, role="editor", invited_by=OWNER_ID),
    ])
    await db_session.flush()

    matrix = {
        "owner": (owner, True, True),
        "editor": (editor, True, True),
        "viewer": (viewer, True, False),
        "stranger": (stranger, False, False),
    }
    for name, (user, can_view, can_edit) in matrix.items():
        assert await _allowed(db_session, collection, user, "viewer") is can_view, f"{name} viewer-level"
        assert await _allowed(db_session, collection, user, "editor") is can_edit, f"{name} editor-level"


@pytest.mark.asyncio
async def test_project_members_inherit_access_unless_collection_is_restricted(db_session):
    project = Project(id=uuid4(), name="p", created_by=OWNER_ID)
    db_session.add(project)
    await db_session.flush()
    member, stranger = await _user(db_session), await _user(db_session)
    db_session.add(ProjectMember(project_id=project.id, user_id=member.id, role="viewer", invited_by=OWNER_ID))
    open_collection = await _collection(db_session, project_id=project.id, restrict_to_members=False)
    restricted = await _collection(db_session, project_id=project.id, restrict_to_members=True)
    await db_session.flush()

    assert await _allowed(db_session, open_collection, member, "viewer") is True
    assert await _allowed(db_session, open_collection, member, "editor") is False  # 프로젝트 viewer는 편집 불가
    assert await _allowed(db_session, open_collection, stranger, "viewer") is False
    assert await _allowed(db_session, restricted, member, "viewer") is False  # 제한된 컬렉션은 상속 안 됨


@pytest.fixture(autouse=True)
def _quiet_http_client_logs():
    import logging

    logging.disable(logging.CRITICAL)
    yield
    logging.disable(logging.NOTSET)
