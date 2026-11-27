"""검색 결과에 붙이는 출처 위치(프로젝트·컬렉션 이름, 쪽 범위, 절 경로) — 실제 Postgres.

2026-11-27: 채팅 인용은 컬렉션·문서 이름, 쪽, 절 경로를 보여 주는데 검색 결과는 문서 이름과 점수만 보였다.
"""
from uuid import uuid4

import pytest

from app.db.models.document_chunk import DocumentChunk
from app.db.models.workflow_run import WorkflowRun
from app.services.search_service import _result_places
from app.services.source_places import chunk_places, collection_places
from tests.unit.api_pg_helpers import (  # noqa: F401
    db_session,
    make_collection,
    make_document,
    make_project,
    make_user,
    make_version,
    make_workflow,
)


async def _world(db):
    owner = await make_user(db, "editor", "owner")
    project = await make_project(db, owner, "항만 사업")
    in_project = await make_collection(db, owner, project, name="규정집")
    loose = await make_collection(db, owner, None, name="개인 자료")
    doc = await make_document(db, owner, in_project, filename="규정.hwp")
    wf = await make_workflow(db, owner, None)
    version = await make_version(db, wf, owner, published=True)
    run = WorkflowRun(version_id=str(version.id), document_id=str(doc.id), status="COMPLETED", trigger="UPLOAD")
    db.add(run)
    await db.flush()
    chunk = DocumentChunk(
        id=uuid4(), document_id=doc.id, run_id=run.id, chunk_order=0, chunk_text="제11조(요양보상) ① …",
        page_start=2, page_end=3, section_path=["제4장 재해보상", "제11조(요양보상)"],
    )
    db.add(chunk)
    await db.flush()
    return dict(project=project, in_project=in_project, loose=loose, doc=doc, chunk=chunk)


@pytest.mark.asyncio
async def test_collection_places_name_the_project_only_for_project_collections(db_session):
    w = await _world(db_session)

    places = await collection_places(db_session, {str(w["in_project"].id), str(w["loose"].id), "not-a-uuid"})

    assert places[str(w["in_project"].id)].project_name == "항만 사업"
    assert places[str(w["in_project"].id)].collection_name == "규정집"
    assert places[str(w["loose"].id)].project_name is None


@pytest.mark.asyncio
async def test_chunk_places_ignore_a_chunk_claimed_by_another_document(db_session):
    w = await _world(db_session)
    chunk_id = str(w["chunk"].id)

    mine = await chunk_places(db_session, {chunk_id: str(w["doc"].id)})
    forged = await chunk_places(db_session, {chunk_id: str(uuid4())})

    assert mine[chunk_id].section_path == ["제4장 재해보상", "제11조(요양보상)"]
    assert (mine[chunk_id].page_start, mine[chunk_id].page_end) == (2, 3)
    assert forged == {}


@pytest.mark.asyncio
async def test_search_results_carry_the_same_place_as_chat_citations(db_session):
    w = await _world(db_session)
    candidates = [
        {"chunk_id": str(w["chunk"].id), "document_id": str(w["doc"].id),
         "metadata": {"filename": "규정.hwp", "collection_id": str(w["in_project"].id), "page_number": 2}},
        # 예전 색인처럼 청크 행이 없으면 페이로드의 시작 쪽만 쓴다
        {"chunk_id": str(uuid4()), "document_id": str(w["doc"].id),
         "metadata": {"filename": "규정.hwp", "collection_id": str(w["in_project"].id), "page_number": 7}},
    ]

    first, old = await _result_places(db_session, candidates)

    assert first == {
        "filename": "규정.hwp", "collection_id": str(w["in_project"].id), "collection_name": "규정집",
        "project_id": str(w["project"].id), "project_name": "항만 사업",
        "page_number": 2, "page_end": 3, "section_path": ["제4장 재해보상", "제11조(요양보상)"],
    }
    assert (old["page_number"], old["page_end"], old["section_path"]) == (7, None, None)
