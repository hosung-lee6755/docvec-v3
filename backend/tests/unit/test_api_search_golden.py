"""search.py / golden_queries.py CRUD 분기 — 실제 Postgres(db_session), 임베딩/Qdrant 모킹."""
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from sqlalchemy import select

from app.api.v1.endpoints import golden_queries as gq_api
from app.api.v1.endpoints import search as search_api
from app.db.models.collection import Collection
from app.db.models.golden_eval_run import GoldenEvalRun
from app.db.models.golden_query import GoldenQuery
from app.db.models.search_history import SearchHistory
from app.schemas.golden_query import GoldenQueryCreate
from app.schemas.search import SearchRequest
from tests.unit._docs_api_support import (
    OWNER_ID,
    add_other_user,
    assert_http_error,
    owner_user,
    stranger_user,
)
from tests.unit._docs_api_support import db_session  # noqa: F401


async def _collection(db) -> Collection:
    collection = Collection(id=uuid4(), name="c", qdrant_collection_name=f"q_{uuid4().hex[:8]}", created_by=OWNER_ID)
    db.add(collection)
    await db.flush()
    return collection


def _golden(collection, query: str, created_at=None) -> GoldenQuery:
    fields = {"created_at": created_at} if created_at else {}
    return GoldenQuery(
        id=uuid4(), collection_id=collection.id, query=query, expected_document_ids=[], created_by=OWNER_ID, **fields
    )


# ------------------------------------------------------------------ search
async def test_search_enforces_rate_limit_checks_scope_then_delegates(db_session):  # noqa: F811
    collection = await _collection(db_session)
    request = SearchRequest(query="계약 해지", collection_id=collection.id)
    expected = MagicMock()

    with (
        patch.object(search_api, "enforce_user_rate_limit") as limiter,
        patch.object(search_api, "perform_search", new=AsyncMock(return_value=expected)) as perform,
    ):
        result = await search_api.search(request, db_session, owner_user())

    assert result is expected
    limiter.assert_called_once_with(OWNER_ID, "search", limit=60, window_seconds=60)
    perform.assert_awaited_once()


async def test_search_rejects_inaccessible_project_and_collection_before_searching(db_session):  # noqa: F811
    collection = await _collection(db_session)

    with patch.object(search_api, "enforce_user_rate_limit"), patch.object(search_api, "perform_search", new=AsyncMock()) as perform:
        await assert_http_error(search_api.search(SearchRequest(query="q", project_id=uuid4()), db_session, owner_user()), 404)
        await assert_http_error(
            search_api.search(SearchRequest(query="q", collection_id=collection.id), db_session, stranger_user()), 403
        )
        await assert_http_error(search_api.search(SearchRequest(query="q", collection_id=uuid4()), db_session, owner_user()), 404)

    perform.assert_not_awaited()


async def test_search_history_returns_own_entries_newest_first_within_limit(db_session):  # noqa: F811
    other = await add_other_user(db_session)
    now = datetime.utcnow()
    for index, user_id in enumerate([OWNER_ID, OWNER_ID, OWNER_ID, other.id]):
        db_session.add(SearchHistory(id=uuid4(), user_id=user_id, query=f"q{index}", created_at=now + timedelta(seconds=index)))
    await db_session.flush()

    result = await search_api.search_history(2, db_session, owner_user())

    assert [item.query for item in result["items"]] == ["q2", "q1"]  # 타인 기록(q3)은 제외, 최신순, limit 적용


# ------------------------------------------------------------ golden queries
async def test_create_golden_query_stores_expected_documents_as_strings(db_session):  # noqa: F811
    collection = await _collection(db_session)
    doc_ids = [uuid4(), uuid4()]

    created = await gq_api.create_golden_query(
        collection.id, GoldenQueryCreate(query="기대 질의", expected_document_ids=doc_ids), db_session, owner_user()
    )

    assert created.expected_document_ids == [str(d) for d in doc_ids]
    assert (str(created.collection_id), str(created.created_by)) == (str(collection.id), OWNER_ID)


async def test_golden_query_endpoints_require_collection_access(db_session):  # noqa: F811
    collection = await _collection(db_session)
    body = GoldenQueryCreate(query="q", expected_document_ids=[uuid4()])

    await assert_http_error(gq_api.create_golden_query(collection.id, body, db_session, stranger_user()), 403)
    await assert_http_error(gq_api.create_golden_query(uuid4(), body, db_session, owner_user()), 404)
    await assert_http_error(gq_api.list_golden_queries(collection.id, db_session, stranger_user()), 403)
    await assert_http_error(gq_api.delete_golden_query(collection.id, uuid4(), db_session, stranger_user()), 403)
    await assert_http_error(gq_api.list_golden_eval_runs(collection.id, db_session, stranger_user()), 403)
    assert (await db_session.scalars(select(GoldenQuery.id))).all() == []


async def test_list_golden_queries_is_scoped_to_collection_newest_first(db_session):  # noqa: F811
    mine, elsewhere = await _collection(db_session), await _collection(db_session)
    now = datetime.utcnow()
    db_session.add_all([
        _golden(mine, "old", now - timedelta(days=1)),
        _golden(mine, "new", now),
        _golden(elsewhere, "other"),
    ])
    await db_session.flush()

    result = await gq_api.list_golden_queries(mine.id, db_session, owner_user())

    assert [q.query for q in result["items"]] == ["new", "old"]


async def test_delete_golden_query_removes_row_and_404s_on_wrong_collection(db_session):  # noqa: F811
    mine, elsewhere = await _collection(db_session), await _collection(db_session)
    gq = _golden(mine, "q")
    db_session.add(gq)
    await db_session.flush()
    gq_id = gq.id

    # 다른 컬렉션 경로로는 지울 수 없다(IDOR 방지)
    await assert_http_error(gq_api.delete_golden_query(elsewhere.id, gq_id, db_session, owner_user()), 404)
    assert await db_session.scalar(select(GoldenQuery.id).where(GoldenQuery.id == gq_id)) is not None

    assert await gq_api.delete_golden_query(mine.id, gq_id, db_session, owner_user()) is None
    assert await db_session.scalar(select(GoldenQuery.id).where(GoldenQuery.id == gq_id)) is None
    await assert_http_error(gq_api.delete_golden_query(mine.id, gq_id, db_session, owner_user()), 404)


async def test_list_golden_eval_runs_caps_at_twenty_newest_first(db_session):  # noqa: F811
    collection = await _collection(db_session)
    now = datetime.utcnow()
    for minute in range(22):
        db_session.add(GoldenEvalRun(
            id=uuid4(), collection_id=collection.id, created_by=OWNER_ID, top_k=minute + 1,
            mean_precision=0.5, mean_recall=0.5, results=[], created_at=now + timedelta(minutes=minute),
        ))
    await db_session.flush()

    result = await gq_api.list_golden_eval_runs(collection.id, db_session, owner_user())

    assert len(result["items"]) == 20
    assert result["items"][0].top_k == 22 and result["items"][-1].top_k == 3


def test_embed_query_returns_first_vector_from_provider():
    provider = MagicMock()
    provider.embed.return_value = [[0.1, 0.2], [9.9]]

    with patch("app.services.embedding.get_embedding_provider", return_value=provider):
        assert gq_api._embed_query("질의") == [0.1, 0.2]

    provider.embed.assert_called_once_with(["질의"])
