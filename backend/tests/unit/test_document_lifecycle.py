"""문서 버전과 수명주기(v3 마일스톤 7) — 검색 가능 판정, 상태 전환, 만료, 버전 API, 목록.

순수 판정, Qdrant 메모리 모드 필터, 실제 Postgres(async API와 sync 워커 경로)를 함께 본다.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.v1.endpoints.documents import lifecycle as lifecycle_api
from app.api.v1.endpoints.documents import listing as listing_api
from app.db.base import Base
from app.db.models.collection import Collection
from app.db.models.document import Document
from app.db.models.user import User
from app.services import document_lifecycle as lc
from app.services.access_payload import point_access_payload
from app.services.access_policy import (
    AccessContext,
    DocumentAccessFacts,
    build_document_facts,
    can_retrieve,
    can_view,
    document_access_payload,
    load_document_facts_sync,
    qdrant_access_filter,
    qdrant_visibility_filter,
    retrievable_document_ids,
    visible_document_ids,
)
from tests.conftest import TEST_DATABASE_URL
from tests.unit._docs_api_support import OWNER_ID, assert_http_error, owner_user, stranger_user
from tests.unit._docs_api_support import db_session  # noqa: F401

SYNC_URL = TEST_DATABASE_URL.replace("+asyncpg", "+psycopg2")
U, COL = "u-1", "c-1"
PAST = datetime.now(timezone.utc) - timedelta(days=1)
FUTURE = datetime.now(timezone.utc) + timedelta(days=30)


def _facts(**over) -> DocumentAccessFacts:
    base = dict(document_id="d", created_by="someone", collection_id=COL, security_level=None,
                collection_default_level=None, acl_principals=frozenset())
    return DocumentAccessFacts(**{**base, **over})


# ------------------------------------------------------------ 순수 판정

@pytest.mark.parametrize("state,expires,expected", [
    ("current", None, True),
    ("current", FUTURE, True),
    ("current", PAST, False),
    ("superseded", None, False),
    ("archived", None, False),
    ("pending", None, False),
])
def test_can_retrieve_requires_current_unexpired_version(state, expires, expected):
    ctx = AccessContext.create(U, [COL], "Internal")
    facts = _facts(lifecycle_state=state, expires_at=expires)

    assert can_view(ctx, facts) is True
    assert can_retrieve(ctx, facts) is expected


def test_uploader_cannot_retrieve_their_own_previous_version():
    ctx = AccessContext.create(U, [], "Public")

    assert can_retrieve(ctx, _facts(created_by=U, lifecycle_state="superseded")) is False
    assert can_retrieve(ctx, _facts(created_by=U)) is True


def test_payload_marks_inactive_versions():
    assert document_access_payload(_facts())["lifecycle"] == "active"
    assert document_access_payload(_facts(lifecycle_state="archived"))["lifecycle"] == "inactive"
    assert document_access_payload(_facts(expires_at=PAST))["lifecycle"] == "inactive"
    assert point_access_payload(None)["lifecycle"] == "inactive"


def test_build_document_facts_defaults_rows_without_lifecycle_to_current():
    old_shape = [("d1", "u", "c", None, None)]
    new_shape = [("d2", "u", "c", None, None, "superseded", None)]

    facts = build_document_facts(old_shape + new_shape, [])

    assert facts["d1"].lifecycle_state == "current"
    assert facts["d2"].lifecycle_state == "superseded"


# ------------------------------------------------------------ Qdrant 필터(메모리 모드)

@pytest.fixture(scope="module")
def qdrant():
    c = QdrantClient(":memory:")
    c.create_collection("t", vectors_config=VectorParams(size=2, distance=Distance.COSINE))
    rows = {
        "current": _facts(document_id="current"),
        "superseded": _facts(document_id="superseded", lifecycle_state="superseded"),
        "archived_mine": _facts(document_id="archived_mine", created_by=U, lifecycle_state="archived"),
    }
    points = [
        PointStruct(id=i, vector=[1.0, 0.0], payload={"document_id": k, **point_access_payload(f)})
        for i, (k, f) in enumerate(rows.items())
    ]
    # 마일스톤 7 이전에 색인된 포인트(lifecycle 필드 없음)는 걸러지지 않는다. Postgres 재확인이 정본이다
    legacy = {k: v for k, v in point_access_payload(_facts()).items() if k != "lifecycle"}
    points.append(PointStruct(id=99, vector=[1.0, 0.0], payload={"document_id": "legacy", **legacy}))
    c.upsert("t", points=points)
    return c


def test_access_and_visibility_filters_drop_inactive_points_even_for_the_uploader(qdrant):
    ctx = AccessContext.create(U, [COL], "Internal")
    for flt in (qdrant_access_filter(ctx), qdrant_visibility_filter(ctx)):
        res = qdrant.query_points("t", query=[1.0, 0.0], limit=10, query_filter=flt)
        assert {p.payload["document_id"] for p in res.points} == {"current", "legacy"}


# ------------------------------------------------------------ async DB(API, 서비스)

async def _collection(db) -> Collection:
    coll = Collection(id=uuid4(), name="c", qdrant_collection_name=f"q_{uuid4().hex[:8]}", created_by=OWNER_ID)
    db.add(coll)
    await db.flush()
    return coll


async def _doc(db, coll, **fields) -> Document:
    defaults = dict(id=uuid4(), filename="보고서.docx", original_filename="보고서.docx", file_size=1,
                    mime_type="text/plain", file_hash=uuid4().hex, minio_key=f"{uuid4()}/r.docx",
                    status="INDEXED", created_by=OWNER_ID, collection_id=coll.id if coll else None)
    doc = Document(**{**defaults, **fields})
    db.add(doc)
    await db.flush()
    return doc


async def _versions(db):
    """v1(이전 버전) → v2(현재 버전) 계보."""
    coll = await _collection(db)
    v1 = await _doc(db, coll, lifecycle_state="superseded", parsed_text="첫째 줄\n매출 300억\n끝")
    v2 = await _doc(db, coll, lineage_id=v1.lineage_id, version_number=2, parsed_text="첫째 줄\n매출 340억\n끝")
    return coll, v1, v2


async def test_same_filename_in_same_collection_becomes_next_pending_version(db_session):  # noqa: F811
    coll, v1, v2 = await _versions(db_session)
    ctx = AccessContext.create(OWNER_ID, [str(coll.id)], "Internal")

    fields, parent = await lc.new_version_fields(db_session, ctx, coll.id, "보고서.docx")

    assert fields == {"lineage_id": v1.lineage_id, "version_number": 3, "lifecycle_state": "pending",
                      "security_level": v2.security_level}
    assert parent.id == v2.id
    assert await lc.new_version_fields(db_session, ctx, coll.id, "다른.docx") == ({}, None)
    assert await lc.new_version_fields(db_session, ctx, None, "보고서.docx") == ({}, None)


async def test_new_version_is_not_linked_when_uploader_cannot_view_the_existing_document(db_session):  # noqa: F811
    coll, _v1, _v2 = await _versions(db_session)
    outsider = AccessContext.create(str(uuid4()), [], "Internal")

    assert await lc.new_version_fields(db_session, outsider, coll.id, "보고서.docx") == ({}, None)


async def test_restore_makes_previous_version_current_and_supersedes_the_current_one(db_session):  # noqa: F811
    _coll, v1, v2 = await _versions(db_session)

    changed = await lc.restore_version(db_session, v1)
    await db_session.commit()
    await db_session.refresh(v2)

    assert (v1.lifecycle_state, v2.lifecycle_state) == ("current", "superseded")
    assert set(changed) == {str(v1.id), str(v2.id)}
    with pytest.raises(lc.LifecycleError):
        await lc.restore_version(db_session, v1)


async def test_restore_rejects_unprocessed_version_and_clears_past_expiry(db_session):  # noqa: F811
    coll = await _collection(db_session)
    failed = await _doc(db_session, coll, lifecycle_state="archived", status="FAILED")
    expired = await _doc(db_session, coll, lifecycle_state="archived", expires_at=PAST)

    with pytest.raises(lc.LifecycleError):
        await lc.restore_version(db_session, failed)
    await lc.restore_version(db_session, expired)

    assert expired.lifecycle_state == "current" and expired.expires_at is None


async def test_archive_only_current_version(db_session):  # noqa: F811
    _coll, v1, v2 = await _versions(db_session)

    assert await lc.archive_document(db_session, v2) == [str(v2.id)]
    assert v2.lifecycle_state == "archived" and v2.archived_at is not None
    with pytest.raises(lc.LifecycleError):
        await lc.archive_document(db_session, v1)


async def test_deleting_current_version_promotes_latest_indexed_previous_one(db_session):  # noqa: F811
    coll, v1, v2 = await _versions(db_session)
    await _doc(db_session, coll, lineage_id=v1.lineage_id, version_number=3, lifecycle_state="superseded",
               status="FAILED")
    lineage = v2.lineage_id
    await db_session.delete(v2)
    await db_session.flush()

    promoted = await lc.promote_after_delete(db_session, lineage, "current")

    assert promoted == [str(v1.id)] and v1.lifecycle_state == "current"
    assert await lc.promote_after_delete(db_session, lineage, "superseded") == []


async def test_versions_endpoint_lists_lineage_with_retrievability(db_session):  # noqa: F811
    _coll, v1, v2 = await _versions(db_session)

    out = await lifecycle_api.list_document_versions(v1.id, db_session, owner_user())

    assert out["lineage_id"] == v1.lineage_id
    assert [(i["version_number"], i["is_retrievable"]) for i in out["items"]] == [(2, True), (1, False)]
    await assert_http_error(lifecycle_api.list_document_versions(v1.id, db_session, stranger_user()), 403)


async def test_compare_returns_line_diff_between_versions(db_session):  # noqa: F811
    coll, v1, v2 = await _versions(db_session)
    unrelated = await _doc(db_session, coll)

    out = await lifecycle_api.compare_document_versions(v2.id, v1.id, db_session, owner_user())

    assert (out["base_version"], out["target_version"]) == (1, 2)
    assert "-매출 300억" in out["diff"] and "+매출 340억" in out["diff"]
    assert (out["added_lines"], out["removed_lines"], out["truncated"]) == (1, 1, False)
    await assert_http_error(
        lifecycle_api.compare_document_versions(v1.id, unrelated.id, db_session, owner_user()), 400
    )


async def test_archive_and_restore_endpoints_sync_payload_and_reject_wrong_state(db_session):  # noqa: F811
    _coll, v1, v2 = await _versions(db_session)

    with patch.object(lifecycle_api, "after_transition", new=AsyncMock()) as after:
        await assert_http_error(lifecycle_api.archive(v1.id, db_session, owner_user()), 409)
        archived = await lifecycle_api.archive(v2.id, db_session, owner_user())
        restored = await lifecycle_api.restore(v1.id, db_session, owner_user())
        await assert_http_error(lifecycle_api.restore(v2.id, db_session, stranger_user()), 403)

    assert archived.lifecycle_state == "archived" and restored.lifecycle_state == "current"
    assert after.await_args_list[0].args[1:] == ([str(v2.id)], v2.collection_id, "lifecycle")


async def test_expiry_must_be_in_the_future_and_can_be_cleared(db_session):  # noqa: F811
    _coll, _v1, v2 = await _versions(db_session)
    req = lifecycle_api.ExpiryRequest

    await assert_http_error(lifecycle_api.set_expiry(v2.id, req(expires_at=PAST), db_session, owner_user()), 422)
    assert (await lifecycle_api.set_expiry(v2.id, req(expires_at=FUTURE), db_session, owner_user())).expires_at
    assert (await lifecycle_api.set_expiry(v2.id, req(expires_at=None), db_session, owner_user())).expires_at is None


async def _list(db, **overrides):
    params = dict(page=1, limit=50, project_id=None, status=None, filename=None, quality=None, lifecycle=None,
                  sort_by="created_at", order="desc")
    return await listing_api.list_documents(db=db, current_user=owner_user(), **{**params, **overrides})


async def test_document_list_hides_previous_versions_unless_asked(db_session):  # noqa: F811
    coll, v1, v2 = await _versions(db_session)

    default = await _list(db_session, collection_id=coll.id)
    everything = await _list(db_session, collection_id=coll.id, lifecycle="all")
    previous = await _list(db_session, collection_id=coll.id, lifecycle="superseded")

    assert [d.id for d in default["items"]] == [v2.id]
    assert {d.id for d in everything["items"]} == {v1.id, v2.id}
    assert [d.id for d in previous["items"]] == [v1.id]


async def test_after_version_delete_promotes_and_schedules(db_session):  # noqa: F811
    coll, v1, v2 = await _versions(db_session)
    removed = [(v2.lineage_id, "current", coll.id)]
    await db_session.delete(v2)
    await db_session.commit()

    with patch("app.services.document_lifecycle.after_transition", new=AsyncMock()) as after:
        await listing_api._after_version_delete(db_session, removed)

    assert v1.lifecycle_state == "current"
    after.assert_awaited_once_with(db_session, [str(v1.id)], coll.id, "document_deleted")


# ------------------------------------------------------------ sync DB(워커 경로)

@pytest.fixture(scope="module")
def session_factory():
    engine = create_engine(SYNC_URL)
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    engine.dispose()


@pytest.fixture
def world(session_factory):
    db = session_factory()
    owner = User(id=uuid4(), email=f"{uuid4()}@example.com", username="o", hashed_password="!", role="viewer",
                 is_active=True)
    db.add(owner)
    db.flush()
    coll = Collection(id=uuid4(), name="w", qdrant_collection_name=f"q-{uuid4()}", created_by=owner.id)
    db.add(coll)
    db.flush()

    def doc(**fields):
        d = Document(id=uuid4(), filename="r.docx", original_filename="r.docx", file_size=1, mime_type="x",
                     file_hash=uuid4().hex, minio_key=f"{uuid4()}/r", status="INDEXED", created_by=owner.id,
                     collection_id=coll.id, **fields)
        db.add(d)
        db.flush()
        return d

    db.commit()
    yield SimpleNamespace(db=db, owner=owner, coll=coll, doc=doc)
    db.close()


def test_indexed_pending_version_becomes_current_and_supersedes_previous(world):
    v1 = world.doc()
    v2 = world.doc(lineage_id=v1.lineage_id, version_number=2, lifecycle_state="pending")
    world.db.commit()

    changed = lc.promote_pending_version_sync(world.db, v2)
    world.db.refresh(v1)

    assert (v1.lifecycle_state, v2.lifecycle_state) == ("superseded", "current")
    assert set(changed) == {str(v1.id), str(v2.id)}
    assert lc.promote_pending_version_sync(world.db, v2) == []


def test_promote_on_indexed_syncs_payload_and_schedules_reevaluation(world):
    v1 = world.doc()
    v2 = world.doc(lineage_id=v1.lineage_id, version_number=2, lifecycle_state="pending")
    world.db.commit()

    with patch("app.services.access_payload.sync_document_access_sync") as sync, \
         patch("app.services.golden_eval.schedule_golden_eval_sync") as schedule:
        lc.promote_on_indexed_sync(world.db, v2)

    assert set(sync.call_args.args[1]) == {str(v1.id), str(v2.id)}
    schedule.assert_called_once_with(world.db, str(world.coll.id), "new_version")


def test_expiry_sweep_archives_only_due_current_documents(world):
    due = world.doc(expires_at=PAST)
    later = world.doc(expires_at=FUTURE)
    already = world.doc(expires_at=PAST, lifecycle_state="superseded")
    world.db.commit()

    expired = lc.expire_due_documents_sync(world.db)

    assert due in expired and later not in expired and already not in expired
    assert due.lifecycle_state == "archived" and due.archived_at is not None


def test_postgres_recheck_and_table_summary_paths_use_current_versions_only(world):
    from app.pipeline.tasks import chat

    current = world.doc()
    old = world.doc(lineage_id=current.lineage_id, version_number=2, lifecycle_state="superseded")
    expired = world.doc(expires_at=PAST)
    world.db.commit()
    ctx = AccessContext.create(str(world.owner.id), [str(world.coll.id)], "Internal")
    facts = load_document_facts_sync(world.db, [str(current.id), str(old.id), str(expired.id)])

    assert visible_document_ids(ctx, facts) == {str(current.id), str(old.id), str(expired.id)}
    assert retrievable_document_ids(ctx, facts) == {str(current.id)}
    found = {str(d.id) for d in chat._accessible_documents(world.db, str(world.owner.id), str(world.coll.id))}
    assert str(current.id) in found and not found & {str(old.id), str(expired.id)}


def test_older_version_finishing_late_does_not_replace_newer_current(world):
    v1 = world.doc()
    v2 = world.doc(lineage_id=v1.lineage_id, version_number=2, lifecycle_state="pending")
    v3 = world.doc(lineage_id=v1.lineage_id, version_number=3, lifecycle_state="pending")
    world.db.commit()

    lc.promote_pending_version_sync(world.db, v3)
    late = lc.promote_pending_version_sync(world.db, v2)

    world.db.refresh(v1)
    assert late == [str(v2.id)]
    assert (v1.lifecycle_state, v2.lifecycle_state, v3.lifecycle_state) == ("superseded", "superseded", "current")


def test_lineage_cannot_have_two_current_versions_or_duplicate_numbers(world):
    from sqlalchemy.exc import IntegrityError

    v1 = world.doc()
    world.db.commit()
    for fields in ({"version_number": 2}, {"version_number": 1, "lifecycle_state": "superseded"}):
        with pytest.raises(IntegrityError):
            world.doc(lineage_id=v1.lineage_id, **fields)
        world.db.rollback()


def test_failed_payload_sync_schedules_a_retry(world):
    v1 = world.doc()
    world.db.commit()

    with patch("app.services.access_payload.sync_document_access_sync", return_value=[str(v1.id)]), \
         patch("app.pipeline.tasks.golden_eval.resync_document_access") as task:
        lc.after_transition_sync(world.db, [str(v1.id)], None, "lifecycle")

    task.apply_async.assert_called_once_with(args=[[str(v1.id)]], countdown=lc.PAYLOAD_RETRY_DELAY_SECONDS)


async def test_connector_documents_reject_lifecycle_changes(db_session):  # noqa: F811
    _coll, _v1, v2 = await _versions(db_session)

    with patch.object(lifecycle_api, "is_connector_lineage", new=AsyncMock(return_value=True)):
        await assert_http_error(lifecycle_api.archive(v2.id, db_session, owner_user()), 409)
        await assert_http_error(
            lifecycle_api.set_expiry(v2.id, lifecycle_api.ExpiryRequest(expires_at=FUTURE), db_session, owner_user()),
            409,
        )


def test_compare_caps_long_lines_and_reports_truncation():
    diff, added, removed, truncated = lifecycle_api._line_diff("x" * 5000, "y")

    assert truncated is True and (added, removed) == (1, 1)
    assert max(len(line) for line in diff) <= lifecycle_api._MAX_COMPARE_LINE_CHARS + 1
