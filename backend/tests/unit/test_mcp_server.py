"""v3 마일스톤 4. 외부 에이전트 연동(MCP)의 개인 접근 토큰과 JSON-RPC 엔드포인트를 검증한다.

권한별 결과(누출)는 누출 매트릭스(test_access_leak_matrix.py)의 MCP 항목이 맡는다.
여기서는 토큰 수명주기, 프로토콜 동작, 감사 기록, 답변 도구의 채널 기록을 본다.
"""
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import select, update

from app.api.v1.endpoints import access_tokens as tokens_api
from app.api.v1.endpoints import chat as chat_api
from app.core.config import settings
from app.core.security import create_access_token
from app.db.models.access_token import PersonalAccessToken
from app.db.models.audit_log import AuditLog
from app.db.models.chat_conversation import ChatConversation
from app.db.models.chat_message import ChatMessage
from app.db.session import get_db
from app.main import app
from app.mcp import server as mcp_server
from app.mcp import tools as mcp_tools
from app.services.access_tokens import TokenRejected, authenticate_token, hash_token
from tests.unit.api_pg_helpers import (  # noqa: F401
    db_session,
    make_collection,
    make_document,
    make_project,
    make_user,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _mcp_on(monkeypatch):
    monkeypatch.setattr(settings, "mcp_enabled", True)
    monkeypatch.setattr(mcp_server, "enforce_user_rate_limit", MagicMock())
    monkeypatch.setattr(tokens_api, "enforce_user_rate_limit", MagicMock())
    monkeypatch.setattr(mcp_server, "enforce_rate_limit", MagicMock())


@pytest.fixture
async def world(db_session):  # noqa: F811
    db = db_session
    alice = await make_user(db, "viewer")
    bob = await make_user(db, "viewer")
    admin = await make_user(db, "admin")
    project = await make_project(db, alice)
    col = await make_collection(db, alice, project)
    await db.commit()
    return SimpleNamespace(db=db, alice=alice, bob=bob, admin=admin, project=project, col=col)


async def _issue(world, user=None, **over):
    body = tokens_api.TokenCreate(**{"name": "내 Claude", **over})
    return await tokens_api.create_my_token(body, world.db, user or world.alice)


@pytest.fixture
async def client(world):
    async def _db():
        yield world.db

    app.dependency_overrides[get_db] = _db
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.pop(get_db, None)


def _rpc(method, params=None, id_=1):
    msg = {"jsonrpc": "2.0", "id": id_, "method": method}
    if params is not None:
        msg["params"] = params
    return msg


async def _post(client, token, message, **headers):
    hdrs = {"Accept": "application/json, text/event-stream", **headers}
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    return await client.post("/api/v1/mcp", json=message, headers=hdrs)


# -- 토큰 ---------------------------------------------------------------------

async def test_token_is_shown_once_and_only_its_hash_is_stored(world):
    out = await _issue(world)

    raw = out["token"]
    assert raw.startswith("dvp_") and len(raw) > 40
    row = await world.db.get(PersonalAccessToken, out["id"])
    assert row.token_hash == hash_token(raw) and raw not in (row.token_prefix + row.token_hash)
    listed = await tokens_api.list_my_tokens(world.db, world.alice)
    assert raw not in str(listed) and listed["items"][0]["status"] == "active"
    audit = (await world.db.scalars(select(AuditLog).where(AuditLog.action == "access_token.create",
                                                           AuditLog.resource_id == out["id"]))).all()
    assert audit and raw not in str(audit[0].detail)


async def test_tokens_cannot_be_issued_when_mcp_is_off_or_over_the_limits(world, monkeypatch):
    with pytest.raises(ValueError):
        tokens_api.TokenCreate(name="x", expires_in_days=settings.mcp_token_max_days + 1)
    monkeypatch.setattr(settings, "mcp_tokens_per_user", 1)
    await _issue(world)
    with pytest.raises(HTTPException) as exc:
        await _issue(world)
    assert exc.value.status_code == 409
    monkeypatch.setattr(settings, "mcp_enabled", False)
    with pytest.raises(HTTPException) as exc:
        await _issue(world, user=world.bob)
    assert exc.value.status_code == 403


async def test_revoked_expired_and_disabled_account_tokens_are_rejected(world):
    raw = (await _issue(world))["token"]
    user, token = await authenticate_token(world.db, raw)
    assert str(user.id) == str(world.alice.id) and token.last_used_at is not None

    # 세션이 커밋 뒤에도 객체를 만료시키지 않으므로 인증이 돌려준 객체를 직접 바꾼다
    user.is_active = False
    await world.db.commit()
    with pytest.raises(TokenRejected):
        await authenticate_token(world.db, raw)
    user.is_active = True
    token.expires_at = datetime.utcnow() - timedelta(seconds=1)
    await world.db.commit()
    with pytest.raises(TokenRejected):
        await authenticate_token(world.db, raw)

    other = await _issue(world)
    await tokens_api.revoke_my_token(other["id"], world.db, world.alice)
    with pytest.raises(TokenRejected):
        await authenticate_token(world.db, other["token"])
    for bad in (None, "", "Bearer x", "dvp_" + "a" * 43):
        with pytest.raises(TokenRejected):
            await authenticate_token(world.db, bad)


async def test_only_the_owner_or_an_admin_can_revoke(world):
    out = await _issue(world)
    with pytest.raises(HTTPException) as exc:
        await tokens_api.revoke_my_token(out["id"], world.db, world.bob)
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        await tokens_api.list_all_tokens(world.db, world.bob)
    assert exc.value.status_code == 403

    listed = await tokens_api.list_all_tokens(world.db, world.admin)
    assert out["id"] in {t["id"] for t in listed["items"]}
    await tokens_api.revoke_any_token(out["id"], world.db, world.admin)
    row = await world.db.get(PersonalAccessToken, out["id"])
    assert row.revoked_at is not None and str(row.revoked_by) == str(world.admin.id)


# -- 프로토콜 ------------------------------------------------------------------

async def test_requests_without_a_valid_token_are_401(world, client):
    no_token = await _post(client, None, _rpc("initialize"))
    assert no_token.status_code == 401 and "Bearer" in no_token.headers["www-authenticate"]
    # 웹 로그인 JWT는 MCP에서 받지 않는다
    jwt = create_access_token({"sub": str(world.alice.id), "email": world.alice.email})
    assert (await _post(client, jwt, _rpc("initialize"))).status_code == 401
    assert (await _post(client, "dvp_" + "x" * 43, _rpc("initialize"))).status_code == 401

    failures = (await world.db.scalars(select(AuditLog).where(AuditLog.action == "mcp.auth_failed"))).all()
    assert [f.detail["token_prefix"] for f in failures] == ["dvp_xxxx"]


async def test_failed_authentication_is_throttled_per_ip(world, client, monkeypatch):
    monkeypatch.setattr(mcp_server, "enforce_rate_limit", MagicMock(side_effect=HTTPException(status_code=429)))
    assert (await _post(client, "dvp_nope", _rpc("ping"))).status_code == 429


async def test_handshake_listing_and_notifications(world, client):
    raw = (await _issue(world))["token"]

    init = (await _post(client, raw, _rpc("initialize", {
        "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"},
    }))).json()
    assert init["result"]["protocolVersion"] == "2025-06-18"
    assert init["result"]["capabilities"]["tools"] == {"listChanged": False}
    newer = (await _post(client, raw, _rpc("initialize", {"protocolVersion": "2099-01-01"}))).json()
    assert newer["result"]["protocolVersion"] == mcp_server.LATEST_VERSION

    note = await _post(client, raw, {"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert note.status_code == 202 and note.content == b""

    tools = (await _post(client, raw, _rpc("tools/list"))).json()["result"]["tools"]
    assert {t["name"] for t in tools} == {"list_collections", "search_documents", "read_chunk",
                                          "read_document", "ask"}
    assert all(t["inputSchema"]["type"] == "object" for t in tools)
    # ask는 대화와 추적 기록을 남기므로 읽기 전용이 아니다
    assert {t["name"]: t["annotations"]["readOnlyHint"] for t in tools}["ask"] is False
    assert all(t["annotations"]["readOnlyHint"] for t in tools if t["name"] != "ask")
    assert (await _post(client, raw, _rpc("ping"))).json()["result"] == {}
    unknown = (await _post(client, raw, _rpc("resources/list"))).json()
    assert unknown["error"]["code"] == -32601


async def test_protocol_errors(world, client):
    raw = (await _issue(world))["token"]
    batch = await client.post("/api/v1/mcp", json=[_rpc("ping")], headers={"Authorization": f"Bearer {raw}"})
    assert batch.status_code == 400
    bad_version = await _post(client, raw, _rpc("ping"), **{"MCP-Protocol-Version": "1999-01-01"})
    assert bad_version.status_code == 400
    foreign = await _post(client, raw, _rpc("ping"), Origin="https://evil.example")
    assert foreign.status_code == 403
    assert (await client.get("/api/v1/mcp")).status_code == 405

    auth = {"Authorization": f"Bearer {raw}", "Content-Type": "application/json"}
    broken = await client.post("/api/v1/mcp", content=b"{not json", headers=auth)
    assert broken.status_code == 400 and broken.json()["error"]["code"] == -32700
    too_big = await client.post("/api/v1/mcp", content=b"{}", headers={**auth, "Content-Length": str(10**7)})
    assert too_big.status_code == 413
    for bad in ({"jsonrpc": "2.0", "id": 1, "method": 5}, {"jsonrpc": "2.0", "id": True, "method": "ping"},
                {"jsonrpc": "2.0", "id": 1}):
        resp = await _post(client, raw, bad)
        assert resp.status_code == 400 and resp.json()["error"]["code"] == -32600
    client_reply = await _post(client, raw, {"jsonrpc": "2.0", "id": 9, "result": {}})
    assert client_reply.status_code == 202


async def test_mcp_off_refuses_every_call(world, client, monkeypatch):
    raw = (await _issue(world))["token"]
    monkeypatch.setattr(settings, "mcp_enabled", False)
    assert (await _post(client, raw, _rpc("ping"))).status_code == 403


async def test_tool_calls_are_audited_including_failures(world, client):
    out = await _issue(world)
    raw = out["token"]

    ok = (await _post(client, raw, _rpc("tools/call", {"name": "list_collections", "arguments": {}}))).json()
    assert ok["result"]["isError"] is False
    bad = (await _post(client, raw, _rpc("tools/call", {"name": "read_chunk", "arguments": {"chunk_id": "x"}}))).json()
    assert bad["result"]["isError"] is True
    missing = (await _post(client, raw, _rpc("tools/call", {
        "name": "read_document", "arguments": {"document_id": str(uuid4())}}))).json()
    assert missing["result"]["isError"] is True
    unknown = (await _post(client, raw, _rpc("tools/call", {"name": "rm_rf"}))).json()
    assert unknown["error"]["code"] == -32602

    rows = (await world.db.scalars(select(AuditLog).where(
        AuditLog.action == "mcp.tool_call", AuditLog.user_id == world.alice.id))).all()
    assert {(r.resource_id, "error" in r.detail) for r in rows} == {
        ("list_collections", False), ("read_chunk", True), ("read_document", True)}
    assert all(r.detail["token_id"] == out["id"] for r in rows)
    # 거절된 요청도 무엇을 열려고 했는지 남는다
    denied = next(r for r in rows if r.resource_id == "read_document")
    assert denied.detail["requested_document_id"]


async def test_rate_limited_calls_are_reported_and_audited(world, client, monkeypatch):
    raw = (await _issue(world))["token"]
    monkeypatch.setattr(mcp_server, "enforce_user_rate_limit", MagicMock(side_effect=HTTPException(status_code=429)))
    resp = (await _post(client, raw, _rpc("tools/call", {"name": "list_collections"}))).json()
    assert resp["result"]["isError"] is True
    row = await world.db.scalar(select(AuditLog).where(AuditLog.action == "mcp.tool_call",
                                                       AuditLog.user_id == world.alice.id))
    assert row.detail["error"] == "rate_limited"


# -- 답변 도구 -----------------------------------------------------------------

def _fake_asyncio(on_sleep):
    clock = iter(range(10_000))
    loop = SimpleNamespace(time=lambda: next(clock))
    return SimpleNamespace(sleep=on_sleep, get_running_loop=lambda: loop)


async def test_ask_answers_through_the_chat_worker_and_is_kept_out_of_web_chat(world, client, monkeypatch):
    out = await _issue(world)
    queued = []

    async def worker_finishes(_seconds):
        # 기다리는 동안에는 트랜잭션을 열어 두지 않는다(연결을 풀에 돌려준다)
        assert not world.db.in_transaction()
        # 채팅 워커 대신 메시지를 완료 상태로 바꾼다
        for message_id in queued:
            await world.db.execute(update(ChatMessage).where(ChatMessage.id == message_id).values(
                status="DONE", answer="연차는 15일입니다[1]",
                citations=[{"index": 1, "document_id": str(uuid4()), "filename": "규정.pdf",
                            "page_number": 3, "text": "연차 15일"}],
            ))
        await world.db.commit()

    monkeypatch.setattr(mcp_tools, "asyncio", _fake_asyncio(worker_finishes))
    with patch("app.pipeline.tasks.chat.generate_answer") as task:
        task.delay.side_effect = queued.append
        resp = (await _post(client, out["token"], _rpc("tools/call", {
            "name": "ask", "arguments": {"question": "연차는 며칠?", "collection_id": str(world.col.id)}}))).json()

    result = resp["result"]["structuredContent"]
    assert result["answer"].startswith("연차는 15일") and result["sources"][0]["filename"] == "규정.pdf"
    conversation = await world.db.scalar(select(ChatConversation).where(
        ChatConversation.user_id == world.alice.id, ChatConversation.channel == "mcp"))
    assert str(conversation.access_token_id) == out["id"]
    assert conversation.model_key == settings.mcp_answer_model
    web_list = await chat_api.list_conversations(project_id=None, db=world.db, current_user=world.alice)
    assert str(conversation.id) not in {str(c.id) for c in web_list}


async def test_ask_times_out_when_the_worker_never_answers(world, client, monkeypatch):
    out = await _issue(world)

    async def nothing(_seconds):
        return None

    monkeypatch.setattr(mcp_tools, "asyncio", _fake_asyncio(nothing))
    monkeypatch.setattr(settings, "mcp_answer_timeout_seconds", 3)
    with patch("app.pipeline.tasks.chat.generate_answer"):
        resp = (await _post(client, out["token"], _rpc("tools/call", {
            "name": "ask", "arguments": {"question": "q", "collection_id": str(world.col.id)}}))).json()
    assert resp["result"]["isError"] is True and "늦어지고" in resp["result"]["content"][0]["text"]


async def test_ask_outside_the_users_scope_is_refused_before_anything_is_queued(world, client):
    raw = (await _issue(world, user=world.bob))["token"]
    with patch("app.pipeline.tasks.chat.generate_answer") as task:
        resp = (await _post(client, raw, _rpc("tools/call", {
            "name": "ask", "arguments": {"question": "q", "collection_id": str(world.col.id)}}))).json()
    assert resp["result"]["isError"] is True
    task.delay.assert_not_called()


def _ask(client, token, question="q", **scope):
    return _post(client, token, _rpc("tools/call", {"name": "ask", "arguments": {"question": question, **scope}}))


async def test_ask_reports_worker_failure_without_internal_details(world, client, monkeypatch):
    out = await _issue(world)
    queued = []

    async def worker_fails(_seconds):
        for message_id in queued:
            await world.db.execute(update(ChatMessage).where(ChatMessage.id == message_id).values(
                status="FAILED", error_message="ConnectionError: vllm-internal.corp:8000 refused"))
        await world.db.commit()

    monkeypatch.setattr(mcp_tools, "asyncio", _fake_asyncio(worker_fails))
    with patch("app.pipeline.tasks.chat.generate_answer") as task:
        task.delay.side_effect = queued.append
        resp = (await _ask(client, out["token"], collection_id=str(world.col.id))).json()
    text = resp["result"]["content"][0]["text"]
    assert resp["result"]["isError"] is True and "vllm-internal" not in text


async def test_ask_marks_the_message_failed_when_the_queue_is_down(world, client):
    out = await _issue(world)
    with patch("app.pipeline.tasks.chat.generate_answer") as task:
        task.delay.side_effect = ConnectionError("broker down")
        resp = (await _ask(client, out["token"], collection_id=str(world.col.id))).json()
    assert resp["result"]["isError"] is True
    message = await world.db.scalar(
        select(ChatMessage).join(ChatConversation, ChatConversation.id == ChatMessage.conversation_id)
        .where(ChatConversation.user_id == world.alice.id, ChatConversation.channel == "mcp"))
    assert message.status == "FAILED"


async def test_ask_limits_how_many_answers_one_person_can_wait_for(world, client):
    out = await _issue(world)
    for _ in range(mcp_tools._MAX_PENDING_ASKS):
        conversation = ChatConversation(user_id=world.alice.id, model_key="m", title="t", channel="mcp")
        world.db.add(conversation)
        await world.db.flush()
        world.db.add(ChatMessage(conversation_id=conversation.id, query="q", status="PENDING"))
    await world.db.commit()
    with patch("app.pipeline.tasks.chat.generate_answer") as task:
        resp = (await _ask(client, out["token"], collection_id=str(world.col.id))).json()
    assert resp["result"]["isError"] is True and "기다리는 질문" in resp["result"]["content"][0]["text"]
    task.delay.assert_not_called()


async def test_deep_ask_runs_in_deep_mode_with_its_own_timeout(world, client, monkeypatch):
    out = await _issue(world)
    seen = await make_document(world.db, world.alice, world.col, filename="a.pdf")
    await world.db.commit()
    queued = []
    waited = []
    docs = [{"document_id": str(seen.id), "filename": "a.pdf"},
            {"document_id": str(uuid4()), "filename": "기밀.pdf"}]  # 지금은 볼 수 없는(없는) 문서

    async def worker_finishes(seconds):
        waited.append(seconds)
        for message_id in queued:
            await world.db.execute(update(ChatMessage).where(ChatMessage.id == message_id).values(
                status="DONE", answer="종합 답[1]", citations=[],
                agent_steps={"subquestions": [{"question": "목표?", "documents": docs}]},
            ))
        await world.db.commit()

    monkeypatch.setattr(mcp_tools, "asyncio", _fake_asyncio(worker_finishes))
    with patch("app.pipeline.tasks.chat.generate_answer") as task:
        task.delay.side_effect = queued.append
        resp = (await _post(client, out["token"], _rpc("tools/call", {"name": "ask", "arguments": {
            "question": "복합 질문", "collection_id": str(world.col.id), "deep": True}}))).json()

    result = resp["result"]["structuredContent"]
    # 지금 볼 수 없는 문서는 이름을 빼고 돌려준다
    assert result["subquestions"] == [{"question": "목표?", "documents": ["a.pdf"]}]
    assert "기밀.pdf" not in str(resp)
    message = await world.db.scalar(
        select(ChatMessage).join(ChatConversation, ChatConversation.id == ChatMessage.conversation_id)
        .where(ChatConversation.user_id == world.alice.id, ChatConversation.channel == "mcp"))
    assert message.mode == "deep"
    audit = await world.db.scalar(select(AuditLog).where(AuditLog.action == "mcp.tool_call",
                                                         AuditLog.resource_id == "ask"))
    assert audit.detail["deep"] is True
