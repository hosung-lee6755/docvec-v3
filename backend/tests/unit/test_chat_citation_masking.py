"""v3 마일스톤 2 — 저장된 대화를 다시 열 때, 지금 볼 수 없는 문서의 인용은 가린다.

답변 본문은 이미 그 사용자에게 보여 준 것이므로 그대로 두고, 인용의 본문·파일명·문서 id만 뺀다.
마일스톤 1의 알려진 제약 17번을 닫는 결정이다.
"""
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.api.v1.endpoints import chat as chat_api
from app.db.models.chat_conversation import ChatConversation
from app.db.models.chat_message import ChatMessage
from tests.unit.api_pg_helpers import (  # noqa: F401
    add_member,
    db_session,
    make_collection,
    make_document,
    make_project,
    make_user,
)

pytestmark = pytest.mark.asyncio


def _citation(index, doc, text):
    return {
        "index": index, "document_id": str(doc.id) if doc else str(uuid4()),
        "collection_id": None, "collection_name": "공유", "filename": f"f{index}.txt",
        "page_number": 1, "text": text,
        # v3 마일스톤 6: 근거 설명의 겹친 낱말은 본문에서 나온 것이라 가린 인용에는 남으면 안 된다
        "evidence": {"scores": {"vector": 0.9}, "matched_terms": [f"낱말{index}"], "ocr_confidence": 0.4, "low_ocr": True},
    }


@pytest.fixture
async def world(db_session):  # noqa: F811
    db = db_session
    owner = await make_user(db, "editor")
    reader = await make_user(db, "viewer")
    project = await make_project(db, owner)
    await add_member(db, project, reader, "viewer", owner)
    col = await make_collection(db, owner, project)
    open_doc = await make_document(db, owner, col)
    later_secret = await make_document(db, owner, col)
    conv = ChatConversation(id=str(uuid4()), user_id=str(reader.id), model_key="qwen2.5-3b", title="t")
    db.add(conv)
    await db.flush()
    msg = ChatMessage(
        id=str(uuid4()), conversation_id=conv.id, query="질문", answer="답[1][2][3]", status="DONE",
        citations=[
            _citation(1, open_doc, "공개 발췌"),
            _citation(2, later_secret, "나중에 대외비가 된 발췌"),
            _citation(3, None, "삭제된 문서 발췌"),
            {**_citation(4, None, "문서 id 없는 발췌"), "document_id": None},
        ],
    )
    db.add(msg)
    # 심층 검색 기록(v3 마일스톤 5)의 문서 목록도 인용과 같은 기준으로 가려야 한다
    msg.mode = "deep"
    msg.agent_steps = {"subquestions": [{"question": "하위 질문", "documents": [
        {"document_id": str(open_doc.id), "filename": "open.pdf"},
        {"document_id": str(later_secret.id), "filename": "later-secret.pdf"},
    ]}]}
    await db.commit()
    # 대화 이후 문서 하나가 대외비로 올라갔다(reader의 열람등급은 Internal)
    later_secret.security_level = "Confidential"
    await db.commit()
    return dict(db=db, reader=reader, conv=conv, msg=msg, open_doc=open_doc)


def _check(citations):
    visible, secret, gone, unknown = citations
    assert (visible.text, visible.filename, visible.hidden) == ("공개 발췌", "f1.txt", False)
    assert visible.evidence["matched_terms"] == ["낱말1"]
    # 문서 id가 없는 인용은 판정할 수 없으므로 가린다(fail-closed)
    for masked in (secret, gone, unknown):
        assert masked.hidden is True
        assert (masked.text, masked.filename, masked.document_id) == ("", None, None)
        assert masked.collection_name is None and masked.index in (2, 3, 4)
        assert masked.evidence is None


async def test_reopened_conversation_masks_citations_now_hidden(world):
    detail = await chat_api.get_conversation(world["conv"].id, world["db"], world["reader"])

    [message] = detail.messages
    assert message.answer == "답[1][2][3]"
    _check(message.citations)
    assert "나중에 대외비가 된 발췌" not in detail.model_dump_json()
    docs = message.agent_steps["subquestions"][0]["documents"]
    assert docs[0]["filename"] == "open.pdf" and docs[1] == {"document_id": None, "filename": None, "hidden": True}
    assert "later-secret.pdf" not in detail.model_dump_json()


async def test_single_message_endpoint_masks_too(world):
    with patch.object(chat_api, "_partial_answer_for", return_value=None):
        message = await chat_api.get_chat_message(world["msg"].id, world["db"], world["reader"])
    _check(message.citations)
