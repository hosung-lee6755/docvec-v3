"""v3 마일스톤 2 — 관리자용 답변 추적 조회 API.

핵심은 추적 상세가 새 누출 경로가 되지 않는 것이다. 관리자도 문서 열람 규칙을 건너뛰지 못하므로,
근거 청크의 현재 본문은 그 관리자가 지금 볼 수 있는 문서일 때만 내려간다.
"""
import hashlib
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api.v1.endpoints import answer_traces as traces_api
from app.db.models.answer_trace import AnswerTrace, AnswerTraceSource
from app.db.models.audit_log import AuditLog
from tests.unit.api_pg_helpers import (  # noqa: F401
    add_member,
    db_session,
    make_collection,
    make_document,
    make_project,
    make_user,
)

pytestmark = pytest.mark.asyncio


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def _trace(db, user, *, query="질문", grounding="passed", created_at=None, sources=()):
    trace = AnswerTrace(
        id=str(uuid4()), user_id=str(user.id), username=user.username, user_role=user.role,
        clearance_level="Internal", group_ids=[], accessible_collection_count=1,
        query=query, answer="답변[1]", status="DONE", grounding=grounding,
        model_key="qwen2.5-3b", provider="local",
        created_at=created_at or datetime.now(timezone.utc),
    )
    db.add(trace)
    await db.flush()
    for rank, src in enumerate(sources, start=1):
        db.add(AnswerTraceSource(trace_id=trace.id, rank=rank, cited=rank == 1, **src))
    await db.flush()
    return trace


@pytest.fixture
async def world(db_session):  # noqa: F811
    db = db_session
    owner = await make_user(db, "editor", username="owner")
    admin = await make_user(db, "admin", username="admin")  # 열람등급 기본값 Internal
    asker = await make_user(db, "viewer", username="asker")
    project = await make_project(db, owner)
    await add_member(db, project, admin, "viewer", owner)
    await add_member(db, project, asker, "viewer", owner)
    col = await make_collection(db, owner, project)
    pub = await make_document(db, owner, col, original_filename="pub.txt",
                              summary="공개 요약", summary_status="DONE")
    conf = await make_document(db, owner, col, original_filename="conf.txt",
                               security_level="Confidential", summary="대외비 요약",
                               summary_status="DONE")
    gone_id = str(uuid4())
    sources = [
        dict(document_id=str(pub.id), collection_id=str(col.id), filename="pub.txt",
             security_level="Public", source_kind="summary", text_sha256=_sha("공개 요약")),
        dict(document_id=str(conf.id), collection_id=str(col.id), filename="conf.txt",
             security_level="Confidential", source_kind="summary", text_sha256=_sha("대외비 요약")),
        dict(document_id=gone_id, filename="gone.txt", security_level="Public",
             source_kind="chunk", chunk_ref=str(uuid4()), text_sha256=_sha("x")),
    ]
    main = await _trace(db, asker, query="근거 질문", sources=sources)
    other = await _trace(db, owner, query="다른 질문", grounding="failed",
                         created_at=datetime.now(timezone.utc) - timedelta(days=3))
    await db.commit()
    return dict(db=db, owner=owner, admin=admin, asker=asker, col=col, pub=pub, conf=conf,
                gone_id=gone_id, main=main, other=other)


async def _list(w, **filters):
    return await traces_api.list_answer_traces(
        db=w["db"], current_user=w["admin"], **{"limit": 50, "offset": 0, **filters}
    )


async def test_non_admin_cannot_list_or_read_traces(world):
    with pytest.raises(HTTPException) as exc:
        await traces_api.list_answer_traces(db=world["db"], current_user=world["asker"])
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException) as exc:
        await traces_api.get_answer_trace(world["main"].id, db=world["db"], current_user=world["owner"])
    assert exc.value.status_code == 403


async def test_list_returns_newest_first_with_counts(world):
    result = await _list(world)
    ids = [i["id"] for i in result["items"]]
    assert ids.index(str(world["main"].id)) < ids.index(str(world["other"].id))
    item = next(i for i in result["items"] if i["id"] == str(world["main"].id))
    assert (item["username"], item["query"], item["source_count"], item["cited_count"]) == (
        "asker", "근거 질문", 3, 1,
    )


async def test_list_filters_by_document_user_grounding_and_date(world):
    by_doc = await _list(world, document_id=str(world["pub"].id))
    assert [i["id"] for i in by_doc["items"]] == [str(world["main"].id)]

    by_col = await _list(world, collection_id=str(world["col"].id))
    assert [i["id"] for i in by_col["items"]] == [str(world["main"].id)]

    by_user = await _list(world, user_id=world["owner"].id)
    assert [i["id"] for i in by_user["items"]] == [str(world["other"].id)]

    failed = await _list(world, grounding="failed")
    assert str(world["other"].id) in [i["id"] for i in failed["items"]]
    assert str(world["main"].id) not in [i["id"] for i in failed["items"]]

    recent = await _list(world, from_date=datetime.now(timezone.utc) - timedelta(days=1))
    assert str(world["other"].id) not in [i["id"] for i in recent["items"]]


async def test_reverse_lookup_by_hidden_document_or_foreign_collection_is_empty(world):
    # 볼 수 없는 문서로 역추적하면 그 문서가 어떤 질문에 쓰였는지 드러난다 → 빈 결과
    assert await _list(world, document_id=str(world["conf"].id)) == {"total": 0, "items": []}
    assert await _list(world, document_id=world["gone_id"]) == {"total": 0, "items": []}
    assert await _list(world, document_id="not-a-uuid") == {"total": 0, "items": []}
    assert await _list(world, collection_id=str(uuid4())) == {"total": 0, "items": []}


async def test_detail_shows_text_only_for_documents_the_admin_can_view(world):
    detail = await traces_api.get_answer_trace(
        world["main"].id, db=world["db"], current_user=world["admin"]
    )
    pub, conf, gone = detail["sources"]

    assert (pub["filename"], pub["access"], pub["text"]) == ("pub.txt", "visible", "공개 요약")
    assert pub["text_changed"] is False

    # 관리자 열람등급(Internal)으로는 대외비 문서를 볼 수 없다 → 본문도, 파일명·등급·위치도 나가면 안 된다
    assert conf["access"] == "hidden" and conf["cited"] is False
    for key in ("document_id", "collection_id", "filename", "security_level", "chunk_ref", "text"):
        assert conf[key] is None and gone[key] is None
    assert "대외비 요약" not in str(detail) and "conf.txt" not in str(detail)

    assert gone["access"] == "deleted" and "gone.txt" not in str(detail)
    assert detail["query"] == "근거 질문" and detail["answer"] == "답변[1]"


def test_source_view_ignores_chunk_text_from_another_document():
    pub_id, other_id, chunk_id = str(uuid4()), str(uuid4()), str(uuid4())
    source = AnswerTraceSource(rank=1, document_id=pub_id, filename="pub.txt", source_kind="chunk",
                               chunk_ref=chunk_id, cited=True, text_sha256=_sha("x"))
    # 청크는 실제로 다른 문서 소속이다 → 기록된 문서가 보이더라도 본문을 쓰면 안 된다
    texts = {"chunk": {f"{other_id}:{chunk_id}": "남의 청크"}, "summary": {}}
    view = traces_api._source_view(source, {pub_id}, {pub_id}, texts)
    assert view["access"] == "visible" and view["text"] is None

    texts = {"chunk": {f"{pub_id}:{chunk_id}": "내 청크"}, "summary": {}}
    assert traces_api._source_view(source, {pub_id}, {pub_id}, texts)["text"] == "내 청크"


async def test_detail_flags_text_changed_since_answer(world):
    world["pub"].summary = "바뀐 요약"
    await world["db"].flush()

    detail = await traces_api.get_answer_trace(
        world["main"].id, db=world["db"], current_user=world["admin"]
    )
    pub = next(s for s in detail["sources"] if s["filename"] == "pub.txt")
    assert pub["text"] == "바뀐 요약" and pub["text_changed"] is True


async def test_detail_view_is_audited(world):
    await traces_api.get_answer_trace(world["main"].id, db=world["db"], current_user=world["admin"])

    rows = (await world["db"].scalars(
        select(AuditLog).where(AuditLog.action == "answer_trace.view")
    )).all()
    assert [(str(r.user_id), r.resource_id) for r in rows] == [
        (str(world["admin"].id), str(world["main"].id))
    ]


async def test_detail_missing_trace_is_404(world):
    with pytest.raises(HTTPException) as exc:
        await traces_api.get_answer_trace(uuid4(), db=world["db"], current_user=world["admin"])
    assert exc.value.status_code == 404


async def test_deep_search_steps_hide_documents_the_admin_cannot_view(world):
    trace = world["main"]
    trace.mode = "deep"
    trace.agent_steps = {"subquestions": [{"question": "하위 질문", "documents": [
        {"document_id": str(world["pub"].id), "filename": "pub.txt"},
        {"document_id": str(world["conf"].id), "filename": "conf.txt"},
    ]}]}
    await world["db"].commit()

    detail = await traces_api.get_answer_trace(trace.id, db=world["db"], current_user=world["admin"])
    listed = await _list(world)

    assert detail["mode"] == "deep"
    docs = detail["agent_steps"]["subquestions"][0]["documents"]
    assert docs[0]["filename"] == "pub.txt" and docs[1] == {"document_id": None, "filename": None, "hidden": True}
    assert "conf.txt" not in str(detail)
    assert {i["id"]: i["mode"] for i in listed["items"]}[str(trace.id)] == "deep"
