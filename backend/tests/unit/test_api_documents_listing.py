"""documents/listing.py — 목록/태그/요약검색/상세/일괄삭제/일괄재처리/삭제. 실제 Postgres(db_session)."""
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.api.v1.endpoints.documents import listing as ls
from app.api.v1.endpoints.documents.models import BatchDeleteRequest, BatchReprocessRequest
from app.db.models.collection import Collection
from app.db.models.document import Document
from app.db.models.processing_job import ProcessingJob
from app.db.models.project import Project
from app.schemas.document import DocumentSummarySearchRequest
from app.services.reprocess_service import ReprocessError
from tests.unit._docs_api_support import (
    OWNER_ID,
    add_doc,
    add_step,
    assert_http_error,
    doc_with_run,
    owner_user,
    stranger_user,
)
from tests.unit._docs_api_support import db_session  # noqa: F401


async def _list(db, user=None, **overrides):
    """엔드포인트를 직접 호출할 때는 Query() 기본값이 적용되지 않으므로 모두 명시한다."""
    params = dict(
        page=1, limit=50, collection_id=None, project_id=None, status=None, filename=None,
        quality=None, lifecycle=None, sort_by="created_at", order="desc",
    )
    params.update(overrides)
    return await ls.list_documents(db=db, current_user=user or owner_user(), **params)


async def _other_user(db):
    from app.db.models.user import User

    user = User(id=str(uuid4()), email=f"{uuid4()}@example.com", username="other", hashed_password="!", role="viewer", is_active=True)
    db.add(user)
    await db.flush()
    return user


async def _collection(db, project_id=None, created_by=OWNER_ID) -> Collection:
    collection = Collection(
        id=uuid4(), name="c", qdrant_collection_name=f"q_{uuid4().hex[:8]}", created_by=created_by, project_id=project_id
    )
    db.add(collection)
    await db.flush()
    return collection


# ---------------------------------------------------------------- list
async def test_list_returns_only_own_documents_in_personal_view(db_session):  # noqa: F811
    mine = await add_doc(db_session, "l-mine", filename="mine.pdf", original_filename="mine.pdf")

    result = await _list(db_session, filename="mine.pdf")
    other_view = await _list(db_session, user=stranger_user(), filename="mine.pdf")

    assert [d.id for d in result["items"]] == [mine.id] and result["total"] == 1
    assert other_view == {"total": 0, "page": 1, "limit": 50, "items": []}


async def test_list_filters_by_status_list_and_collection(db_session):  # noqa: F811
    collection = await _collection(db_session)
    a = await add_doc(db_session, "l-st-a", status="FAILED", original_filename="zzq-a.pdf", collection_id=collection.id)
    b = await add_doc(db_session, "l-st-b", status="PARSING", original_filename="zzq-b.pdf", collection_id=collection.id)
    await add_doc(db_session, "l-st-c", status="INDEXED", original_filename="zzq-c.pdf", collection_id=collection.id)

    result = await _list(db_session, collection_id=collection.id, status="FAILED,PARSING,")

    assert {d.id for d in result["items"]} == {a.id, b.id}


async def test_list_filters_by_quality_and_counts_low_ocr_pages(db_session):  # noqa: F811
    from app.schemas.document import DocumentResponse

    collection = await _collection(db_session)
    pages = lambda *c: [{"page_number": i + 1, "confidence": v, "word_count": 5} for i, v in enumerate(c)]  # noqa: E731
    low = await add_doc(db_session, "l-q-low", collection_id=collection.id, ocr_used=True,
                        ocr_page_confidence=pages(0.9, 0.31, 0.2), quality_status="PARTIAL_FAILURE")
    good = await add_doc(db_session, "l-q-good", collection_id=collection.id, ocr_used=True,
                         ocr_page_confidence=pages(0.9, 0.8), quality_status="SUCCESS")
    failed = await add_doc(db_session, "l-q-fail", collection_id=collection.id, quality_status="FAILURE")

    async def ids(quality):
        return {d.id for d in (await _list(db_session, collection_id=collection.id, quality=quality))["items"]}

    assert await ids("low_ocr") == {low.id}
    assert await ids("warning") == {low.id}
    assert await ids("failure") == {failed.id}
    assert await ids(None) == {low.id, good.id, failed.id}
    dumped = DocumentResponse.model_validate(low).model_dump()
    assert dumped["low_ocr_pages"] == 2 and "ocr_page_confidence" not in dumped
    assert dumped["quality_status"] == "PARTIAL_FAILURE"


async def test_ocr_confidence_endpoint_lists_pages_and_flags_low_ones(db_session):  # noqa: F811
    from app.api.v1.endpoints.documents import processing

    doc = await add_doc(db_session, "l-ocr", ocr_used=True, page_count=3, ocr_page_confidence=[
        {"page_number": 2, "confidence": 0.42, "word_count": 7},
        {"page_number": 1, "confidence": 0.88, "word_count": 30},
    ])

    out = await processing.get_document_ocr_confidence(doc.id, db=db_session, current_user=owner_user())

    assert [p.page_number for p in out.pages] == [1, 2]
    assert out.low_pages == [2] and out.threshold == 0.5 and out.mean_confidence == 0.65
    with pytest.raises(Exception) as denied:
        await processing.get_document_ocr_confidence(doc.id, db=db_session, current_user=stranger_user())
    assert getattr(denied.value, "status_code", None) in (403, 404)


async def test_list_filename_search_escapes_like_wildcards(db_session):  # noqa: F811
    literal = await add_doc(db_session, "l-fn-1", original_filename="qq100%_final.pdf")
    await add_doc(db_session, "l-fn-2", original_filename="qq100XXfinal.pdf")

    result = await _list(db_session, filename="100%_final")

    assert [d.id for d in result["items"]] == [literal.id]


async def test_list_sorts_and_paginates(db_session):  # noqa: F811
    collection = await _collection(db_session)
    for name in ("b.pdf", "c.pdf", "a.pdf"):
        await add_doc(db_session, f"l-sort-{name}", original_filename=name, collection_id=collection.id)

    asc_page1 = await _list(db_session, collection_id=collection.id, sort_by="filename", order="asc", limit=2)
    asc_page2 = await _list(db_session, collection_id=collection.id, sort_by="filename", order="asc", limit=2, page=2)
    desc_all = await _list(db_session, collection_id=collection.id, sort_by="filename", order="desc")

    assert [d.original_filename for d in asc_page1["items"]] == ["a.pdf", "b.pdf"]
    assert [d.original_filename for d in asc_page2["items"]] == ["c.pdf"]
    assert asc_page1["total"] == 3 and asc_page2["page"] == 2
    assert [d.original_filename for d in desc_all["items"]] == ["c.pdf", "b.pdf", "a.pdf"]


async def test_list_includes_documents_of_collections_the_user_can_access(db_session):  # noqa: F811
    collection = await _collection(db_session)  # 소유자: OWNER
    foreign = await add_doc(db_session, "l-shared", collection_id=collection.id, original_filename="shared-zq.pdf")
    foreign.created_by = (await _other_user(db_session)).id  # 다른 사람이 올렸지만 내 컬렉션 안의 문서
    await db_session.flush()

    result = await _list(db_session, user=owner_user(), filename="shared-zq")

    assert [d.id for d in result["items"]] == [foreign.id]


async def test_list_by_project_scopes_to_project_collections(db_session):  # noqa: F811
    project = Project(id=uuid4(), name="proj", created_by=OWNER_ID)
    empty_project = Project(id=uuid4(), name="empty", created_by=OWNER_ID)
    db_session.add_all([project, empty_project])
    await db_session.flush()
    in_project = await _collection(db_session, project_id=project.id)
    doc_in = await add_doc(db_session, "l-proj-in", collection_id=in_project.id)
    await add_doc(db_session, "l-proj-out")  # 프로젝트 밖 문서

    scoped = await _list(db_session, project_id=project.id)
    empty = await _list(db_session, project_id=empty_project.id)

    assert [d.id for d in scoped["items"]] == [doc_in.id]
    assert empty == {"total": 0, "page": 1, "limit": 50, "items": []}
    await assert_http_error(_list(db_session, project_id=uuid4()), 404)
    await assert_http_error(_list(db_session, user=stranger_user(), project_id=project.id), 403)


# ---------------------------------------------------------------- tags
async def test_list_all_tags_is_sorted_distinct_and_scoped_to_accessible_documents(db_session):  # noqa: F811
    await add_doc(db_session, "t-1", tags=["zeta", "alpha"])
    await add_doc(db_session, "t-2", tags=["alpha", "beta"])
    await add_doc(db_session, "t-3")  # 태그 없음

    mine = await ls.list_all_tags(db_session, owner_user())
    theirs = await ls.list_all_tags(db_session, stranger_user())

    assert mine["tags"] == ["alpha", "beta", "zeta"]
    assert theirs == {"tags": []}


# ------------------------------------------------------- summary search
def _hit(doc_id, score: float, summary: str = "요약") -> dict:
    return {"score": score, "payload": {"document_id": str(doc_id), "summary": summary}}


async def test_summary_search_returns_empty_when_index_has_no_hits(db_session):  # noqa: F811
    with patch("app.services.summary_index.search_document_summaries", return_value=[]):
        result = await ls.search_documents_by_summary(DocumentSummarySearchRequest(query="계약"), db_session, owner_user())

    assert result == {"items": []}


async def test_summary_search_filters_hits_to_accessible_documents(db_session):  # noqa: F811
    mine = await add_doc(db_session, "s-mine")
    foreign = await add_doc(db_session, "s-foreign")
    foreign.created_by = (await _other_user(db_session)).id
    await db_session.flush()
    hits = [_hit(foreign.id, 0.99), _hit(mine.id, 0.8, "내 문서 요약"), {"score": 0.1, "payload": {}}]

    with patch("app.services.summary_index.search_document_summaries", return_value=hits) as search:
        result = await ls.search_documents_by_summary(
            DocumentSummarySearchRequest(query="계약", limit=3), db_session, owner_user()
        )

    search.assert_called_once()
    query, limit, query_filter = search.call_args.args
    assert (query, limit) == ("계약", 3)
    assert query_filter is not None  # v3: 권한 필터 없이 요약 인덱스를 검색하면 안 된다
    assert result["items"] == [{"document_id": str(mine.id), "score": 0.8, "summary": "내 문서 요약"}]


# ------------------------------------------------------------ get_document
async def test_get_document_reconciles_stuck_run_and_returns_document(db_session):  # noqa: F811
    doc = await add_doc(db_session, "g-doc")

    with patch("app.services.reprocess_service.reconcile_stuck_run", new=AsyncMock()) as reconcile:
        result = await ls.get_document(doc.id, db_session, owner_user())

    assert result.id == doc.id
    reconcile.assert_awaited_once()


async def test_get_document_404_and_403_skip_reconcile(db_session):  # noqa: F811
    doc = await add_doc(db_session, "g-doc-403")

    with patch("app.services.reprocess_service.reconcile_stuck_run", new=AsyncMock()) as reconcile:
        await assert_http_error(ls.get_document(uuid4(), db_session, owner_user()), 404)
        await assert_http_error(ls.get_document(doc.id, db_session, stranger_user()), 403)

    reconcile.assert_not_awaited()


# ------------------------------------------------- delete (external cleanup)
@pytest.fixture
def externals(monkeypatch):
    """Qdrant/요약 인덱스/MinIO 모킹 — 호출 기록을 SimpleNamespace로 돌려준다."""
    qdrant, storage, summary = MagicMock(), MagicMock(), MagicMock()
    release = AsyncMock()
    monkeypatch.setattr("app.services.qdrant_service.qdrant_service", qdrant)
    monkeypatch.setattr("app.services.storage.storage_service", storage)
    monkeypatch.setattr("app.services.summary_index.delete_document_summary", summary)
    monkeypatch.setattr(ls, "release_original", release)
    return SimpleNamespace(qdrant=qdrant, storage=storage, summary=summary, release=release)


async def test_delete_document_404_403_and_collection_owner_may_delete(db_session, externals):  # noqa: F811
    collection = await _collection(db_session, created_by=OWNER_ID)
    own = await add_doc(db_session, "d-own")
    foreign_doc = await add_doc(db_session, "d-foreign", collection_id=collection.id)
    stranger = stranger_user()

    await assert_http_error(ls.delete_document(uuid4(), db_session, owner_user()), 404)
    await assert_http_error(ls.delete_document(own.id, db_session, stranger), 403)
    # 컬렉션 소유자가 아닌 사용자는 컬렉션 안 문서도 삭제 불가
    await assert_http_error(ls.delete_document(foreign_doc.id, db_session, stranger), 403)
    externals.release.assert_not_awaited()


async def test_delete_document_tolerates_external_cleanup_failures(db_session, externals):  # noqa: F811
    doc = await add_doc(
        db_session, "d-ext", images=[{"page_number": 1, "storage_key": "img1"}, {"page_number": 2, "storage_key": "img2"}]
    )
    doc_id = doc.id
    db_session.add(ProcessingJob(id=uuid4(), document_id=doc_id, job_type="parse", status="COMPLETED"))
    await db_session.flush()
    externals.qdrant.delete_by_document.side_effect = RuntimeError("no collection")
    externals.summary.side_effect = RuntimeError("no summary index")
    externals.storage.delete_file.side_effect = [RuntimeError("minio down"), None]

    result = await ls.delete_document(doc_id, db_session, owner_user())

    assert result == {"message": "Document deleted"}
    assert await db_session.scalar(select(Document.id).where(Document.id == doc_id)) is None
    assert await db_session.scalar(select(ProcessingJob.id).where(ProcessingJob.document_id == doc_id)) is None
    assert externals.storage.delete_file.call_count == 2  # 첫 이미지 실패해도 다음 이미지를 계속 지운다
    externals.release.assert_awaited_once()


# ------------------------------------------------------------ batch delete
async def test_batch_delete_only_removes_documents_the_user_may_delete(db_session, externals):  # noqa: F811
    other = await _other_user(db_session)
    mine = await add_doc(db_session, "bd-mine", images=[{"page_number": 1, "storage_key": "k"}])
    theirs = await add_doc(db_session, "bd-theirs", created_by=other.id)
    mine_id, theirs_id = mine.id, theirs.id
    externals.qdrant.delete_by_document.side_effect = RuntimeError("qdrant down")
    externals.summary.side_effect = RuntimeError("summary down")
    externals.storage.delete_file.side_effect = RuntimeError("minio down")

    result = await ls.batch_delete_documents(BatchDeleteRequest(ids=[mine_id, theirs_id]), db_session, owner_user())

    assert result == {"deleted": 1, "message": "1 documents deleted"}
    remaining = set((await db_session.scalars(select(Document.id).where(Document.id.in_([mine_id, theirs_id])))).all())
    assert remaining == {theirs_id}


async def test_batch_delete_collection_owner_can_remove_members_documents(db_session, externals):  # noqa: F811
    other = await _other_user(db_session)
    collection = await _collection(db_session, created_by=OWNER_ID)
    doc = await add_doc(db_session, "bd-coll", created_by=other.id, collection_id=collection.id)
    doc_id = doc.id

    result = await ls.batch_delete_documents(BatchDeleteRequest(ids=[doc_id]), db_session, owner_user())

    assert result["deleted"] == 1
    assert await db_session.scalar(select(Document.id).where(Document.id == doc_id)) is None


# ---------------------------------------------------------- batch reprocess
async def _failed_doc_with_step(db, key: str):
    doc, run = await doc_with_run(db, key, status="FAILED")
    step = await add_step(db, run)
    step.status = "FAILED"
    step.completed_at = datetime.utcnow()
    await db.flush()
    return doc, run, step


async def test_batch_reprocess_reports_each_document_outcome(db_session):  # noqa: F811
    missing = uuid4()
    forbidden = await add_doc(db_session, "br-403")
    healthy = await add_doc(db_session, "br-ok", status="INDEXED")
    no_run = await add_doc(db_session, "br-norun", status="FAILED")
    no_step, _ = await doc_with_run(db_session, "br-nostep", status="FAILED")
    queued_doc, run, step = await _failed_doc_with_step(db_session, "br-queued")
    new_run = SimpleNamespace(id=uuid4())
    ids = [missing, forbidden.id, healthy.id, no_run.id, no_step.id, queued_doc.id]

    with (
        patch("app.services.reprocess_service.resolve_start_block", new=AsyncMock(return_value="blk")) as resolve,
        patch("app.services.reprocess_service.start_partial_reprocess", new=AsyncMock(return_value=new_run)) as start,
    ):
        # forbidden 문서는 stranger가 호출할 때만 403 — 소유자 호출로 하나, 나머지는 stranger로 확인
        owner_result = await ls.batch_reprocess_documents(BatchReprocessRequest(ids=ids), db_session, owner_user())
        stranger_result = await ls.batch_reprocess_documents(BatchReprocessRequest(ids=[forbidden.id]), db_session, stranger_user())

    by_id = {r.id: r for r in owner_result.results}
    assert by_id[missing].status == "failed" and "찾을 수 없" in by_id[missing].detail
    assert by_id[healthy.id].status == "skipped" and "INDEXED" in by_id[healthy.id].detail
    assert by_id[no_run.id].status == "skipped"  # active_run_id 없음
    assert by_id[no_step.id].status == "failed" and "실패한 블록" in by_id[no_step.id].detail
    assert by_id[queued_doc.id].status == "queued" and by_id[queued_doc.id].run_id == new_run.id
    resolve.assert_awaited_once()
    assert resolve.await_args.args[1:] == (run.version_id, None, step.block_instance_id)
    assert start.await_args.kwargs["reason"] == "실패 목록 일괄 재처리"
    assert stranger_result.results[0].status == "failed"  # 접근 거부는 목록의 개별 실패로 보고


async def test_batch_reprocess_maps_reprocess_error_and_missing_parent_run(db_session):  # noqa: F811
    broken, _, _ = await _failed_doc_with_step(db_session, "br-err")
    orphan, _, _ = await _failed_doc_with_step(db_session, "br-orphan")

    with patch("app.services.reprocess_service.resolve_start_block", new=AsyncMock(side_effect=ReprocessError("시작 블록 없음"))):
        error_result = await ls.batch_reprocess_documents(BatchReprocessRequest(ids=[broken.id]), db_session, owner_user())
    with patch.object(db_session, "get", new=AsyncMock(return_value=None)):
        orphan_result = await ls.batch_reprocess_documents(BatchReprocessRequest(ids=[orphan.id]), db_session, owner_user())

    assert (error_result.results[0].status, error_result.results[0].detail) == ("failed", "시작 블록 없음")
    assert orphan_result.results[0].status == "failed" and "실행 기록" in orphan_result.results[0].detail

