"""chat.py 엔드포인트 — 실제 Postgres(db_session), Celery/Redis 모킹."""
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.api.v1.endpoints import chat as chat_api
from app.db.models.chat_conversation import ChatConversation
from app.db.models.chat_message import ChatMessage
from app.db.models.collection import Collection
from app.db.models.project import Project
from app.db.models.project_api_key import ProjectApiKey
from app.db.models.user_api_key import UserApiKey
from tests.unit._docs_api_support import OWNER_ID, add_other_user, assert_http_error, owner_user, stranger_user
from tests.unit._docs_api_support import db_session  # noqa: F401

GENERATE = "app.pipeline.tasks.chat.generate_answer"
RATE_LIMIT = "app.core.rate_limit.enforce_user_rate_limit"


async def _project(db, created_by=OWNER_ID) -> Project:
    project = Project(id=uuid4(), name="p", created_by=created_by)
    db.add(project)
    await db.flush()
    return project


async def _conversation(db, user_id=OWNER_ID, title="대화", project_id=None, updated_at=None) -> ChatConversation:
    conversation = ChatConversation(
        id=uuid4(), user_id=user_id, project_id=project_id, model_key="qwen2.5-3b", title=title,
        updated_at=updated_at or datetime.utcnow(),
    )
    db.add(conversation)
    await db.flush()
    return conversation


async def _message(db, conversation, query="질문", status="DONE", created_at=None) -> ChatMessage:
    msg = ChatMessage(
        id=uuid4(), conversation_id=conversation.id, query=query, status=status, created_at=created_at or datetime.utcnow()
    )
    db.add(msg)
    await db.flush()
    return msg


# ---------------------------------------------------------------- helpers
def test_derive_title_trims_flattens_newlines_and_truncates():
    assert chat_api._derive_title("  안녕\n하세요  ") == "안녕 하세요"
    long_title = chat_api._derive_title("가" * 100)
    assert long_title == "가" * chat_api._TITLE_MAX_LEN + "..."
    assert chat_api._derive_title("나" * chat_api._TITLE_MAX_LEN) == "나" * chat_api._TITLE_MAX_LEN  # 경계값은 말줄임 없음


def test_partial_answer_reads_decoded_value_from_redis(monkeypatch):
    monkeypatch.setattr(chat_api, "_partial_redis", None)
    client = MagicMock()
    client.get.return_value = "부분 답변".encode()

    with patch("redis.from_url", return_value=client):
        assert chat_api._partial_answer_for("m1") == "부분 답변"

    client.get.assert_called_once_with("chat_partial:m1")


def test_partial_answer_is_none_when_missing_or_redis_fails(monkeypatch):
    client = MagicMock()
    client.get.return_value = None
    monkeypatch.setattr(chat_api, "_partial_redis", client)
    assert chat_api._partial_answer_for("m1") is None

    client.get.side_effect = ConnectionError("redis down")
    assert chat_api._partial_answer_for("m1") is None  # 스트리밍 미리보기 실패는 요청을 깨뜨리지 않는다


def test_message_with_partial_only_looks_up_generating_messages():
    base = dict(id=uuid4(), query="q", answer=None, citations=None, error_message=None, created_at=datetime.utcnow())

    with patch.object(chat_api, "_partial_answer_for", return_value="조각") as lookup:
        generating = chat_api._message_with_partial(SimpleNamespace(status="GENERATING", **base))
        done = chat_api._message_with_partial(SimpleNamespace(status="DONE", **base))

    assert generating.partial_answer == "조각" and done.partial_answer is None
    lookup.assert_called_once()


# ------------------------------------------------- _validate_model_and_key
async def test_validate_rejects_unknown_model(db_session):  # noqa: F811
    await assert_http_error(chat_api._validate_model_and_key(db_session, owner_user(), "no-such-model"), 422)


async def test_validate_local_model_needs_no_key(db_session):  # noqa: F811
    await chat_api._validate_model_and_key(db_session, owner_user(), "qwen2.5-3b")


async def test_validate_cloud_model_requires_user_or_project_key(db_session):  # noqa: F811
    project = await _project(db_session)
    err = await assert_http_error(chat_api._validate_model_and_key(db_session, owner_user(), "gpt-4o-mini", project.id), 422)
    assert "openai" in err.detail

    db_session.add(ProjectApiKey(id=uuid4(), project_id=project.id, provider="openai", encrypted_key="x"))
    await db_session.flush()
    await chat_api._validate_model_and_key(db_session, owner_user(), "gpt-4o-mini", project.id)  # 프로젝트 키 우선
    await assert_http_error(chat_api._validate_model_and_key(db_session, owner_user(), "gpt-4o-mini"), 422)  # 프로젝트 없이는 여전히 없음

    db_session.add(UserApiKey(id=uuid4(), user_id=OWNER_ID, provider="openai", encrypted_key="x"))
    await db_session.flush()
    await chat_api._validate_model_and_key(db_session, owner_user(), "gpt-4o-mini")


# -------------------------------------------------------------- models
async def test_list_models_marks_cloud_models_available_per_registered_key(db_session):  # noqa: F811
    db_session.add(UserApiKey(id=uuid4(), user_id=OWNER_ID, provider="anthropic", encrypted_key="x"))
    await db_session.flush()

    result = await chat_api.list_chat_models(None, db_session, owner_user())

    availability = {item["key"]: item["available"] for item in result["items"]}
    assert availability["qwen2.5-3b"] is True
    assert availability["claude-3-5-haiku"] is True
    assert availability["gpt-4o-mini"] is False
    assert result["default_system_prompt"]


async def test_list_models_includes_project_keys_and_checks_project_access(db_session):  # noqa: F811
    project = await _project(db_session)
    db_session.add(ProjectApiKey(id=uuid4(), project_id=project.id, provider="openai", encrypted_key="x"))
    await db_session.flush()

    result = await chat_api.list_chat_models(project.id, db_session, owner_user())

    assert {i["key"]: i["available"] for i in result["items"]}["gpt-4o"] is True
    await assert_http_error(chat_api.list_chat_models(uuid4(), db_session, owner_user()), 404)
    await assert_http_error(chat_api.list_chat_models(project.id, db_session, stranger_user()), 403)


# ------------------------------------------------- create_conversation
async def test_create_conversation_persists_pending_message_and_dispatches(db_session):  # noqa: F811
    project = await _project(db_session)
    data = chat_api.CreateConversationRequest(query="가" * 80, project_id=project.id, model_key="qwen2.5-3b")

    with patch(GENERATE) as task:
        result = await chat_api.create_conversation(data, db_session, owner_user())

    assert result.title == "가" * 60 + "..." and result.project_id == project.id
    [message] = result.messages
    assert (message.status, message.query) == ("PENDING", "가" * 80)
    task.delay.assert_called_once_with(str(message.id))
    stored = await db_session.scalar(select(ChatConversation).where(ChatConversation.id == result.id))
    assert str(stored.user_id) == OWNER_ID


async def test_create_conversation_rejects_bad_model_project_and_collection(db_session):  # noqa: F811
    project = await _project(db_session)
    with patch(GENERATE) as task:
        await assert_http_error(
            chat_api.create_conversation(chat_api.CreateConversationRequest(query="q", model_key="nope"), db_session, owner_user()), 422
        )
        await assert_http_error(
            chat_api.create_conversation(
                chat_api.CreateConversationRequest(query="q", model_key="qwen2.5-3b", project_id=project.id), db_session, stranger_user()
            ), 403,
        )
        await assert_http_error(
            chat_api.create_conversation(
                chat_api.CreateConversationRequest(query="q", model_key="qwen2.5-3b", collection_id=uuid4()), db_session, owner_user()
            ), 404,
        )
    task.delay.assert_not_called()
    assert (await db_session.scalars(select(ChatConversation.id))).all() == []


async def test_create_conversation_with_accessible_collection(db_session):  # noqa: F811
    collection = Collection(id=uuid4(), name="c", qdrant_collection_name="q_chat", created_by=OWNER_ID)
    db_session.add(collection)
    await db_session.flush()
    data = chat_api.CreateConversationRequest(query="q", model_key="qwen2.5-3b", collection_id=collection.id)

    with patch(GENERATE):
        result = await chat_api.create_conversation(data, db_session, owner_user())

    assert result.collection_id == collection.id


# ------------------------------------------------------ list / get
async def test_list_conversations_separates_personal_and_project_history(db_session):  # noqa: F811
    project = await _project(db_session)
    other = await add_other_user(db_session)
    now = datetime.utcnow()
    older = await _conversation(db_session, title="오래된 개인", updated_at=now - timedelta(hours=1))
    newer = await _conversation(db_session, title="최근 개인", updated_at=now)
    scoped = await _conversation(db_session, title="프로젝트", project_id=project.id)
    await _conversation(db_session, user_id=other.id, title="남의 대화")

    personal = await chat_api.list_conversations(None, db_session, owner_user())
    in_project = await chat_api.list_conversations(project.id, db_session, owner_user())

    assert [c.id for c in personal] == [newer.id, older.id]
    assert [c.id for c in in_project] == [scoped.id]
    await assert_http_error(chat_api.list_conversations(project.id, db_session, stranger_user()), 403)


async def test_get_conversation_returns_messages_oldest_first(db_session):  # noqa: F811
    conversation = await _conversation(db_session)
    now = datetime.utcnow()
    second = await _message(db_session, conversation, "둘째", created_at=now)
    first = await _message(db_session, conversation, "첫째", created_at=now - timedelta(minutes=1))

    result = await chat_api.get_conversation(conversation.id, db_session, owner_user())

    assert [m.id for m in result.messages] == [first.id, second.id]


async def test_get_conversation_404_and_403(db_session):  # noqa: F811
    conversation = await _conversation(db_session)

    await assert_http_error(chat_api.get_conversation(uuid4(), db_session, owner_user()), 404)
    await assert_http_error(chat_api.get_conversation(conversation.id, db_session, stranger_user()), 403)


# ---------------------------------------------------------- rename/delete
async def test_rename_conversation_trims_and_truncates_title(db_session):  # noqa: F811
    conversation = await _conversation(db_session)

    result = await chat_api.rename_conversation(
        conversation.id, chat_api.RenameConversationRequest(title="  " + "x" * 100 + "  "), db_session, owner_user()
    )

    assert result.title == "x" * chat_api._TITLE_MAX_LEN


async def test_rename_conversation_rejects_blank_title_and_foreign_access(db_session):  # noqa: F811
    conversation = await _conversation(db_session, title="원래 제목")

    await assert_http_error(
        chat_api.rename_conversation(conversation.id, chat_api.RenameConversationRequest(title="   "), db_session, owner_user()), 422
    )
    await assert_http_error(
        chat_api.rename_conversation(conversation.id, chat_api.RenameConversationRequest(title="x"), db_session, stranger_user()), 403
    )
    assert conversation.title == "원래 제목"


async def test_delete_conversation_removes_messages_too(db_session):  # noqa: F811
    conversation = await _conversation(db_session)
    await _message(db_session, conversation)
    conversation_id = conversation.id

    await chat_api.delete_conversation(conversation_id, db_session, owner_user())

    assert await db_session.scalar(select(ChatConversation.id).where(ChatConversation.id == conversation_id)) is None
    assert (await db_session.scalars(select(ChatMessage.id).where(ChatMessage.conversation_id == conversation_id))).all() == []


async def test_delete_conversation_forbidden_for_non_owner(db_session):  # noqa: F811
    conversation = await _conversation(db_session)

    await assert_http_error(chat_api.delete_conversation(conversation.id, db_session, stranger_user()), 403)
    await assert_http_error(chat_api.delete_conversation(uuid4(), db_session, owner_user()), 404)
    assert await db_session.get(ChatConversation, conversation.id) is not None


# ------------------------------------------------------------- messages
async def test_create_message_queues_generation_and_touches_conversation(db_session):  # noqa: F811
    conversation = await _conversation(db_session, updated_at=datetime.utcnow() - timedelta(days=1))
    before = conversation.updated_at

    with patch(GENERATE) as task, patch(RATE_LIMIT) as limiter:
        msg = await chat_api.create_message(conversation.id, chat_api.CreateMessageRequest(query="후속 질문"), db_session, owner_user())

    assert (msg.status, msg.query) == ("PENDING", "후속 질문")
    task.delay.assert_called_once_with(str(msg.id))
    limiter.assert_called_once_with(OWNER_ID, "chat_message", limit=30, window_seconds=60)
    await db_session.refresh(conversation)
    assert conversation.updated_at.replace(tzinfo=None) > before  # UTCDateTime은 tz-aware로 돌려준다


async def test_create_message_forbidden_or_missing_conversation_dispatches_nothing(db_session):  # noqa: F811
    conversation = await _conversation(db_session)
    body = chat_api.CreateMessageRequest(query="q")

    with patch(GENERATE) as task, patch(RATE_LIMIT):
        await assert_http_error(chat_api.create_message(conversation.id, body, db_session, stranger_user()), 403)
        await assert_http_error(chat_api.create_message(uuid4(), body, db_session, owner_user()), 404)

    task.delay.assert_not_called()


async def test_create_message_propagates_rate_limit_rejection(db_session):  # noqa: F811
    from fastapi import HTTPException

    conversation = await _conversation(db_session)

    with patch(GENERATE) as task, patch(RATE_LIMIT, side_effect=HTTPException(status_code=429, detail="slow down")):
        await assert_http_error(
            chat_api.create_message(conversation.id, chat_api.CreateMessageRequest(query="q"), db_session, owner_user()), 429
        )

    task.delay.assert_not_called()


async def test_get_chat_message_returns_own_message_with_partial_when_generating(db_session):  # noqa: F811
    conversation = await _conversation(db_session)
    msg = await _message(db_session, conversation, status="GENERATING")

    with patch.object(chat_api, "_partial_answer_for", return_value="생성 중...") as lookup:
        result = await chat_api.get_chat_message(msg.id, db_session, owner_user())

    assert result.partial_answer == "생성 중..."
    lookup.assert_called_once_with(msg.id)


async def test_get_chat_message_404_and_403(db_session):  # noqa: F811
    conversation = await _conversation(db_session)
    msg = await _message(db_session, conversation)

    await assert_http_error(chat_api.get_chat_message(uuid4(), db_session, owner_user()), 404)
    await assert_http_error(chat_api.get_chat_message(msg.id, db_session, stranger_user()), 403)


@pytest.mark.parametrize("status", ["PENDING", "DONE", "FAILED"])
async def test_get_chat_message_does_not_query_redis_for_non_generating_status(db_session, status):  # noqa: F811
    conversation = await _conversation(db_session)
    msg = await _message(db_session, conversation, status=status)

    with patch.object(chat_api, "_partial_answer_for") as lookup:
        result = await chat_api.get_chat_message(msg.id, db_session, owner_user())

    assert result.status == status and result.partial_answer is None
    lookup.assert_not_called()


async def test_create_message_keeps_the_requested_deep_mode(db_session):  # noqa: F811
    conversation = await _conversation(db_session)
    with patch(GENERATE), patch(RATE_LIMIT):
        msg = await chat_api.create_message(
            conversation.id, chat_api.CreateMessageRequest(query="복합 질문", mode="deep"), db_session, owner_user())
    assert msg.mode == "deep"
    stored = await db_session.get(ChatMessage, msg.id)
    assert stored.mode == "deep"


def test_generating_deep_message_carries_its_progress():
    base = dict(id=uuid4(), query="q", answer=None, citations=None, error_message=None, created_at=datetime.utcnow())
    progress = {"phase": "searching", "subquestions": ["a?", "b?"], "current": 1}
    with patch.object(chat_api, "_partial_answer_for", return_value=None),          patch.object(chat_api, "_progress_for", return_value=progress) as lookup:
        deep = chat_api._message_with_partial(SimpleNamespace(status="GENERATING", mode="deep", agent_steps=None, **base))
        plain = chat_api._message_with_partial(SimpleNamespace(status="GENERATING", mode="standard", agent_steps=None, **base))
    assert deep.progress == progress and plain.progress is None
    lookup.assert_called_once()
