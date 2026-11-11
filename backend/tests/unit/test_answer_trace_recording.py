"""v3 마일스톤 2 — 채팅 답변마다 추적 기록이 남는지 검증한다.

test_task_chat.py의 실제 Postgres 픽스처(world, chat_env)와 가짜 LLM(ScriptedProvider)을 그대로 쓴다.
"""
import hashlib
import json
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.db.models.answer_trace import AnswerTrace, AnswerTraceSource
from app.db.models.chat_conversation import ChatConversation
from app.db.models.chat_message import ChatMessage
from app.db.models.llm_usage_log import LLMUsageLog
from app.pipeline.tasks import chat
from app.services.access_policy import build_access_context_sync
from tests.unit.test_task_chat import (  # noqa: F401
    CHUNK,
    ScriptedProvider,
    _document,
    chat_env,
    session_factory,
    world,
)


@pytest.fixture(autouse=True)
def _cleanup(world):
    """이 파일은 실제로 커밋한다. 알파벳순으로 뒤에 도는 API 테스트(빈 테이블을 가정하는 것 포함)를
    깨지 않도록, 테스트가 만든 대화·메시지·추적 기록을 지운다."""
    yield
    db = world.factory()
    user_ids = [world.alice.id, world.bob.id, world.carol.id, world.stranger.id]
    db.query(AnswerTrace).filter(AnswerTrace.user_id.in_(user_ids)).delete(synchronize_session=False)
    db.query(LLMUsageLog).filter(LLMUsageLog.user_id.in_(user_ids)).delete(synchronize_session=False)
    conv_ids = [c for (c,) in db.query(ChatConversation.id).filter(ChatConversation.user_id.in_(user_ids))]
    if conv_ids:
        db.query(ChatMessage).filter(ChatMessage.conversation_id.in_(conv_ids)).delete(synchronize_session=False)
        db.query(ChatConversation).filter(ChatConversation.id.in_(conv_ids)).delete(synchronize_session=False)
    db.commit()
    db.close()


def _trace_for(db, msg_id) -> AnswerTrace:
    return db.query(AnswerTrace).filter_by(chat_message_id=msg_id).one()


def _sources(db, trace) -> list[AnswerTraceSource]:
    return (
        db.query(AnswerTraceSource).filter_by(trace_id=trace.id)
        .order_by(AnswerTraceSource.rank).all()
    )


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_done_answer_records_who_access_model_and_sources(chat_env, world):
    conv, msg = chat_env.build(collection=world.c_own)
    second = {**CHUNK, "filename": "b.pdf", "text": "다른 발췌", "chunk_ref": "p-2", "score": 0.4}

    chat_env.run(msg.id, ScriptedProvider(), retrieve=MagicMock(return_value=[CHUNK, second]))

    db = world.factory()
    trace = _trace_for(db, msg.id)
    expected_ctx = build_access_context_sync(db, str(world.alice.id))
    assert (trace.status, trace.query, trace.answer) == ("DONE", "질문입니다", "정답입니다[1]")
    assert (trace.user_id, trace.username, trace.user_role) == (world.alice.id, "alice", "viewer")
    assert trace.conversation_id == conv.id
    assert trace.scope_collection_id == world.c_own.id
    assert trace.clearance_level == "Internal"
    assert trace.access_fingerprint == expected_ctx.fingerprint()
    assert trace.accessible_collection_count == len(expected_ctx.collection_ids)
    assert (trace.intent, trace.grounding, trace.broadened) == ("chunk_search", "passed", False)
    assert (trace.cache_hit, trace.model_key, trace.provider) == (False, "qwen2.5-3b", "local")
    assert trace.system_prompt_source == "default"
    assert trace.system_prompt_sha256 == _sha(chat._SYSTEM_PROMPT)
    assert trace.latency_ms is not None and trace.latency_ms >= 0

    sources = _sources(db, trace)
    assert [(s.rank, s.filename, s.cited) for s in sources] == [(1, "a.pdf", True), (2, "b.pdf", False)]
    assert sources[0].text_sha256 == _sha("본문 발췌")
    assert (sources[1].chunk_ref, sources[1].score) == ("p-2", 0.4)
    db.close()


def test_source_keeps_effective_security_level_at_answer_time(chat_env, world):
    _conv, msg = chat_env.build()
    doc = _document(world.db, world.alice, world.c_own, security_level="Confidential")
    world.db.commit()
    chunk = {**CHUNK, "document_id": str(doc.id), "collection_id": str(world.c_own.id)}

    chat_env.run(msg.id, ScriptedProvider(), retrieve=MagicMock(return_value=[chunk]))

    db = world.factory()
    [source] = _sources(db, _trace_for(db, msg.id))
    assert source.security_level == "Confidential"
    db.close()


def test_cache_hit_is_traced_with_cached_citations(chat_env, world):
    _conv, msg = chat_env.build()
    redis_hit = MagicMock()
    redis_hit.get.return_value = json.dumps({
        "answer": "캐시 답[1]",
        "citations": [{"index": 1, "filename": "c.pdf", "text": "캐시 발췌"}],
    })

    chat_env.run(msg.id, ScriptedProvider(), redis_=redis_hit)

    db = world.factory()
    trace = _trace_for(db, msg.id)
    assert (trace.cache_hit, trace.status, trace.answer) == (True, "DONE", "캐시 답[1]")
    [source] = _sources(db, trace)
    assert (source.source_kind, source.filename, source.cited) == ("cached", "c.pdf", True)
    db.close()


def test_ungrounded_answer_records_failed_grounding_and_broadening(chat_env, world):
    _conv, msg = chat_env.build()
    provider = ScriptedProvider(grounded=("INSUFFICIENT",), stream_answers=("첫 답[1]", "확장 답[1]"))
    broader = {**CHUNK, "filename": "wide.pdf"}

    chat_env.run(msg.id, provider, retrieve=MagicMock(side_effect=[[CHUNK], [broader]]))

    db = world.factory()
    trace = _trace_for(db, msg.id)
    assert (trace.grounding, trace.broadened, trace.answer) == ("failed", True, "확장 답[1]")
    assert [s.filename for s in _sources(db, trace)] == ["wide.pdf"]
    db.close()


def test_nothing_retrieved_records_skipped_grounding(chat_env, world):
    _conv, msg = chat_env.build()

    chat_env.run(msg.id, ScriptedProvider(), retrieve=MagicMock(return_value=[]))

    db = world.factory()
    trace = _trace_for(db, msg.id)
    assert trace.grounding == "skipped" and _sources(db, trace) == []
    db.close()


def test_cloud_generation_records_tokens_and_verifier(chat_env, world):
    _conv, msg = chat_env.build(model_key="gpt-4o-mini")
    provider = ScriptedProvider(usage={"input_tokens": 1000, "output_tokens": 500})

    with patch.object(chat, "_find_api_key", return_value="sk-test"):
        chat_env.run(msg.id, provider)

    db = world.factory()
    trace = _trace_for(db, msg.id)
    assert (trace.provider, trace.verifier_model) == ("openai", "gpt-4o-mini")
    assert (trace.input_tokens, trace.output_tokens) == (1000, 500)
    db.close()


def test_project_prompt_source_is_recorded(chat_env, world):
    world.project.system_prompt = "PROJECT PROMPT"
    world.db.merge(world.project)
    world.db.commit()
    _conv, msg = chat_env.build(project=world.project)

    chat_env.run(msg.id, ScriptedProvider())

    db = world.factory()
    trace = _trace_for(db, msg.id)
    assert trace.system_prompt_source == "project"
    assert trace.system_prompt_sha256 == _sha("PROJECT PROMPT")
    assert trace.scope_project_id == world.project.id
    db.close()


def test_failed_answer_is_traced_with_error(chat_env, world):
    _conv, msg = chat_env.build(model_key="no-such-model")

    chat_env.run(msg.id, ScriptedProvider())

    db = world.factory()
    trace = _trace_for(db, msg.id)
    assert trace.status == "FAILED" and "Unknown model" in trace.error_message
    assert trace.answer is None
    db.close()


def test_trace_survives_conversation_deletion(chat_env, world):
    conv, msg = chat_env.build()
    chat_env.run(msg.id, ScriptedProvider())

    db = world.factory()
    trace_id = _trace_for(db, msg.id).id
    db.execute(ChatMessage.__table__.delete().where(ChatMessage.conversation_id == conv.id))
    db.delete(db.get(ChatConversation, conv.id))
    db.commit()
    db.close()

    db = world.factory()
    trace = db.get(AnswerTrace, trace_id)
    assert trace is not None and trace.chat_message_id is None
    assert trace.conversation_id == conv.id and trace.answer == "정답입니다[1]"
    assert len(_sources(db, trace)) == 1
    db.close()


def test_trace_failure_does_not_break_the_answer(chat_env, world):
    _conv, msg = chat_env.build()

    with patch("app.services.answer_trace.AnswerTrace", side_effect=RuntimeError("boom")):
        result, _ = chat_env.run(msg.id, ScriptedProvider())

    stored, db = chat_env.reload(msg.id)
    assert result["status"] == "DONE" and stored.status == "DONE"
    assert db.query(AnswerTrace).filter_by(chat_message_id=msg.id).count() == 0
    db.close()


def test_unknown_message_writes_no_trace(chat_env, world):
    missing = uuid4()
    chat_env.run(missing, ScriptedProvider())

    db = world.factory()
    assert db.query(AnswerTrace).filter_by(chat_message_id=missing).count() == 0
    db.close()
