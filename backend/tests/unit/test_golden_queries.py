"""골든 평가 API(v3 마일스톤 7) — 실행 예약, 기준 지정, 질의 수정, 기대 문서 검증. 실제 Postgres."""
from unittest.mock import patch
from uuid import uuid4

from app.api.v1.endpoints import golden_queries as gq_api
from app.db.models.collection import Collection
from app.db.models.document import Document
from app.db.models.golden_eval_run import GoldenEvalRun
from app.db.models.golden_query import GoldenQuery
from app.schemas.golden_query import GoldenEvalRunRequest, GoldenQueryCreate, GoldenQueryUpdate
from tests.unit._docs_api_support import OWNER_ID, assert_http_error, owner_user, stranger_user
from tests.unit._docs_api_support import db_session  # noqa: F401


async def _collection(db, **fields) -> Collection:
    collection = Collection(
        id=uuid4(), name="c", qdrant_collection_name=f"q_{uuid4().hex[:8]}", created_by=OWNER_ID, **fields
    )
    db.add(collection)
    await db.flush()
    return collection


async def _doc(db, collection) -> Document:
    doc = Document(
        id=uuid4(), filename="a.txt", original_filename="a.txt", file_size=1, mime_type="text/plain",
        file_hash="h" * 64, minio_key=f"{uuid4()}/a.txt", status="INDEXED", created_by=OWNER_ID,
        collection_id=collection.id,
    )
    db.add(doc)
    await db.flush()
    return doc


async def _golden(db, collection, expected=None) -> GoldenQuery:
    gq = GoldenQuery(
        id=uuid4(), collection_id=collection.id, query="질의", expected_document_ids=expected or [],
        created_by=OWNER_ID,
    )
    db.add(gq)
    await db.flush()
    return gq


def _run(collection, **fields) -> GoldenEvalRun:
    defaults = dict(id=uuid4(), collection_id=collection.id, created_by=OWNER_ID, top_k=5, status="DONE")
    return GoldenEvalRun(**{**defaults, **fields})


async def test_run_queues_manual_evaluation_with_collection_top_k_and_enqueues(db_session):  # noqa: F811
    collection = await _collection(db_session, search_settings={"top_k": 7})
    await _golden(db_session, collection)

    with patch("app.core.rate_limit.enforce_user_rate_limit"), patch.object(gq_api, "enqueue_run") as enqueue:
        run = await gq_api.run_golden_eval(collection.id, GoldenEvalRunRequest(), db_session, owner_user())

    assert (run.status, run.trigger, run.top_k) == ("QUEUED", "manual", 7)
    assert run.mean_recall is None and run.results is None
    enqueue.assert_called_once_with(str(run.id))


async def test_run_uses_requested_top_k_over_collection_setting(db_session):  # noqa: F811
    collection = await _collection(db_session, search_settings={"top_k": 7})
    await _golden(db_session, collection)

    with patch("app.core.rate_limit.enforce_user_rate_limit"), patch.object(gq_api, "enqueue_run"):
        run = await gq_api.run_golden_eval(collection.id, GoldenEvalRunRequest(top_k=3), db_session, owner_user())

    assert run.top_k == 3


async def test_run_rejects_collection_without_golden_queries_and_strangers(db_session):  # noqa: F811
    collection = await _collection(db_session)

    with patch("app.core.rate_limit.enforce_user_rate_limit"), patch.object(gq_api, "enqueue_run") as enqueue:
        await assert_http_error(
            gq_api.run_golden_eval(collection.id, GoldenEvalRunRequest(), db_session, owner_user()), 400
        )
        await assert_http_error(
            gq_api.run_golden_eval(collection.id, GoldenEvalRunRequest(), db_session, stranger_user()), 403
        )
    enqueue.assert_not_called()


async def test_baseline_requires_finished_run_and_moves_the_flag(db_session):  # noqa: F811
    collection = await _collection(db_session)
    old, new, queued = _run(collection, is_baseline=True), _run(collection), _run(collection, status="QUEUED")
    db_session.add_all([old, new, queued])
    await db_session.flush()

    await assert_http_error(gq_api.set_golden_baseline(collection.id, queued.id, db_session, owner_user()), 409)
    result = await gq_api.set_golden_baseline(collection.id, new.id, db_session, owner_user())

    assert result["is_baseline"] is True
    await db_session.refresh(old)
    assert old.is_baseline is False
    await assert_http_error(gq_api.set_golden_baseline(collection.id, uuid4(), db_session, owner_user()), 404)


async def test_get_run_is_scoped_to_collection(db_session):  # noqa: F811
    mine, elsewhere = await _collection(db_session), await _collection(db_session)
    run = _run(mine)
    db_session.add(run)
    await db_session.flush()

    assert (await gq_api.get_golden_eval_run(mine.id, run.id, db_session, owner_user()))["id"] == run.id
    await assert_http_error(gq_api.get_golden_eval_run(elsewhere.id, run.id, db_session, owner_user()), 404)


async def test_update_changes_query_and_expected_documents(db_session):  # noqa: F811
    collection = await _collection(db_session)
    doc = await _doc(db_session, collection)
    gq = await _golden(db_session, collection)

    updated = await gq_api.update_golden_query(
        collection.id, gq.id, GoldenQueryUpdate(query="고친 질의", expected_document_ids=[doc.id]),
        db_session, owner_user(),
    )

    assert (updated.query, updated.expected_document_ids) == ("고친 질의", [str(doc.id)])
    await assert_http_error(
        gq_api.update_golden_query(collection.id, gq.id, GoldenQueryUpdate(query="x"), db_session, stranger_user()),
        403,
    )


async def test_expected_documents_must_belong_to_the_collection(db_session):  # noqa: F811
    mine, elsewhere = await _collection(db_session), await _collection(db_session)
    foreign = await _doc(db_session, elsewhere)
    gq = await _golden(db_session, mine)

    await assert_http_error(
        gq_api.create_golden_query(
            mine.id, GoldenQueryCreate(query="q", expected_document_ids=[foreign.id]), db_session, owner_user()
        ),
        400,
    )
    await assert_http_error(
        gq_api.update_golden_query(
            mine.id, gq.id, GoldenQueryUpdate(expected_document_ids=[uuid4()]), db_session, owner_user()
        ),
        400,
    )


async def test_golden_queries_are_capped_per_collection(db_session):  # noqa: F811
    collection = await _collection(db_session)
    doc = await _doc(db_session, collection)
    await _golden(db_session, collection)

    with patch.object(gq_api, "MAX_GOLDEN_QUERIES_PER_COLLECTION", 1):
        await assert_http_error(
            gq_api.create_golden_query(
                collection.id, GoldenQueryCreate(query="q", expected_document_ids=[doc.id]), db_session, owner_user()
            ),
            409,
        )


async def test_expected_documents_must_be_visible_to_the_requester(db_session):  # noqa: F811
    collection = await _collection(db_session)
    doc = await _doc(db_session, collection)

    with patch.object(gq_api, "_visible_ids", return_value=({str(doc.id)}, set())):
        await assert_http_error(
            gq_api.create_golden_query(
                collection.id, GoldenQueryCreate(query="q", expected_document_ids=[doc.id]), db_session, owner_user()
            ),
            400,
        )


def test_mask_result_hides_ids_and_scores_tied_to_hidden_expected_documents():
    row = {"golden_query_id": "g", "query": "q", "expected_document_ids": ["a", "hidden"],
           "retrieved_document_ids": ["hidden", "a", "gone"], "precision": 0.5, "recall": 1.0,
           "hit": True, "reciprocal_rank": 1.0, "first_hit_rank": 1}

    masked = gq_api._mask_result(row, existing={"a", "hidden"}, visible={"a"})
    deleted_only = gq_api._mask_result({**row, "expected_document_ids": ["a", "gone"]}, {"a"}, {"a"})

    assert masked["expected_document_ids"] == ["a"] and masked["retrieved_document_ids"] == ["a"]
    assert masked["masked"] is True and masked["hit"] is None and masked["recall"] is None
    # 지워진 기대 문서는 숨길 대상이 아니므로 점수를 그대로 둔다
    assert deleted_only["hit"] is True and "masked" not in deleted_only
