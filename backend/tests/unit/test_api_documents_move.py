"""문서를 다른 컬렉션으로 옮기기 (2026-11-17 요청)."""
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api.v1.endpoints.documents import move as move_api
from app.api.v1.endpoints.documents.models import BatchMoveRequest
from app.db.models.audit_log import AuditLog
from app.db.models.collection import Collection
from app.db.models.collection_member import CollectionMember
from app.db.models.document import Document
from app.db.models.user import User
from tests.unit._docs_api_support import OWNER_ID, add_doc, owner_user
from tests.unit._docs_api_support import db_session  # noqa: F401


@pytest.fixture
def pushed(monkeypatch):
    """Qdrant에 보낸 (문서 id, 페이로드)."""
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr("app.services.access_payload._push_payload", lambda doc_id, payload: calls.append((doc_id, payload)))
    return calls


async def _collection(db, created_by=OWNER_ID, **fields):
    collection = Collection(id=uuid4(), name="c", qdrant_collection_name=f"q_{uuid4().hex[:8]}",
                            created_by=created_by, **fields)
    db.add(collection)
    await db.flush()
    return collection


async def _move(db, ids, target, user=None):
    return await move_api.batch_move_documents(
        BatchMoveRequest(ids=ids, collection_id=target.id), db, user or owner_user("editor"),
    )


async def _collection_of(db, doc_id):
    return await db.scalar(
        select(Document.collection_id).where(Document.id == doc_id).execution_options(populate_existing=True)
    )


async def test_moves_the_document_with_its_other_versions_and_updates_the_search_index(db_session, pushed):  # noqa: F811
    source, target = await _collection(db_session), await _collection(db_session)
    v1 = await add_doc(db_session, "mv-1", collection_id=source.id, lifecycle_state="superseded")
    v2 = await add_doc(db_session, "mv-2", collection_id=source.id, lineage_id=v1.id, version_number=2)
    v1_id, v2_id = v1.id, v2.id

    await db_session.commit()
    result = await _move(db_session, [v2_id], target)

    assert [r.status for r in result.results] == ["moved"]
    assert str(await _collection_of(db_session, v2_id)) == str(target.id)
    assert str(await _collection_of(db_session, v1_id)) == str(target.id)
    assert {doc_id for doc_id, _ in pushed} == {str(v1_id), str(v2_id)}
    assert all(payload["collection_id"] == str(target.id) for _, payload in pushed)
    audit = await db_session.scalar(select(AuditLog).where(AuditLog.action == "document.move"))
    assert audit is not None and audit.detail["versions"] == 2


async def test_skips_documents_that_are_being_processed_or_already_there(db_session, pushed):  # noqa: F811
    source, target = await _collection(db_session), await _collection(db_session)
    busy = await add_doc(db_session, "mv-busy", collection_id=source.id, status="EMBEDDING")
    already = await add_doc(db_session, "mv-here", collection_id=target.id, file_hash="z" * 64)

    await db_session.commit()
    result = await _move(db_session, [busy.id, already.id], target)

    assert [r.status for r in result.results] == ["skipped", "skipped"]
    assert "처리 중" in result.results[0].detail and "이미" in result.results[1].detail
    assert pushed == []


async def test_refuses_a_move_that_would_put_the_same_file_twice_in_one_collection(db_session, pushed):  # noqa: F811
    source, target = await _collection(db_session), await _collection(db_session)
    await add_doc(db_session, "mv-dup-there", collection_id=target.id, file_hash="d" * 64)
    doc = await add_doc(db_session, "mv-dup", collection_id=source.id, file_hash="d" * 64)

    await db_session.commit()
    result = await _move(db_session, [doc.id], target)

    assert result.results[0].status == "skipped" and "같은 파일" in result.results[0].detail
    assert str(await _collection_of(db_session, doc.id)) == str(source.id)


async def test_refuses_collections_with_a_different_embedding_model(db_session, pushed):  # noqa: F811
    source = await _collection(db_session, embedding_model="bge-m3")
    target = await _collection(db_session, embedding_model="other-model")
    doc = await add_doc(db_session, "mv-model", collection_id=source.id)

    await db_session.commit()
    result = await _move(db_session, [doc.id], target)

    assert result.results[0].status == "skipped" and "임베딩 모델" in result.results[0].detail


async def test_needs_editor_access_to_the_target_collection(db_session, pushed):  # noqa: F811
    source = await _collection(db_session)
    foreign = await _collection(db_session, created_by=await _other_user(db_session))
    doc = await add_doc(db_session, "mv-foreign", collection_id=source.id)

    with pytest.raises(HTTPException) as exc:
        await _move(db_session, [doc.id], foreign)

    assert exc.value.status_code == 403
    assert str(await _collection_of(db_session, doc.id)) == str(source.id)


async def test_a_member_cannot_relax_an_inherited_security_level_by_moving(db_session, pushed):  # noqa: F811
    # 보안등급을 상속하던 문서를 더 느슨한 컬렉션으로 옮기면 더 많은 사람이 보게 된다
    member_id = await _other_user(db_session)
    source = await _collection(db_session, default_security_level="Confidential")
    target = await _collection(db_session, default_security_level="Public")
    for collection in (source, target):
        db_session.add(CollectionMember(collection_id=collection.id, user_id=member_id,
                                        role="editor", invited_by=OWNER_ID))
    await db_session.flush()
    doc = await add_doc(db_session, "mv-relax", collection_id=source.id)
    member = owner_user("editor")
    member.id = member_id

    await db_session.commit()
    result = await _move(db_session, [doc.id], target, user=member)

    assert result.results[0].status == "failed"
    assert str(await _collection_of(db_session, doc.id)) == str(source.id)


async def test_rolls_back_when_the_search_index_cannot_be_updated(db_session, monkeypatch):  # noqa: F811
    source, target = await _collection(db_session), await _collection(db_session)
    doc = await add_doc(db_session, "mv-qdrant-down", collection_id=source.id)
    doc_id, source_id, target_id = doc.id, str(source.id), str(target.id)
    await db_session.commit()
    pushed: list[str] = []

    def push(doc_id, payload):
        pushed.append(payload["collection_id"])
        if payload["collection_id"] == target_id:
            raise RuntimeError("qdrant down")

    monkeypatch.setattr("app.services.access_payload._push_payload", push)

    await db_session.commit()
    result = await _move(db_session, [doc_id], target)

    assert result.results[0].status == "failed" and "색인" in result.results[0].detail
    assert str(await _collection_of(db_session, doc_id)) == source_id
    # 되돌린 뒤 원래 컬렉션 값으로 포인트를 다시 맞춘다
    assert pushed[-1] == source_id


async def _other_user(db) -> str:
    user_id = str(uuid4())
    db.add(User(id=user_id, email=f"{user_id}@example.com", username=f"u{user_id[:8]}", hashed_password="!",
                role="viewer", is_active=True))
    await db.flush()
    return user_id


async def test_a_failed_move_does_not_break_the_rest_of_the_batch(db_session, monkeypatch):  # noqa: F811
    # 리뷰 H1: 실패한 문서를 되돌린 뒤에도 다음 문서를 그대로 옮긴다
    source, target = await _collection(db_session), await _collection(db_session)
    first = await add_doc(db_session, "mv-batch-1", collection_id=source.id, file_hash="1" * 64)
    second = await add_doc(db_session, "mv-batch-2", collection_id=source.id, file_hash="2" * 64)
    first_id, second_id, target_id = first.id, second.id, str(target.id)
    await db_session.commit()

    def push(doc_id, payload):
        if doc_id == str(first_id) and payload["collection_id"] == target_id:
            raise RuntimeError("qdrant down")

    monkeypatch.setattr("app.services.access_payload._push_payload", push)

    result = await _move(db_session, [first_id, second_id], target)

    assert [r.status for r in result.results] == ["failed", "moved"]
    assert str(await _collection_of(db_session, second_id)) == target_id


async def test_a_version_still_being_processed_blocks_moving_the_lineage(db_session, pushed):  # noqa: F811
    # 리뷰 H2: 함께 옮기는 다른 버전도 같은 검사를 거친다
    source, target = await _collection(db_session), await _collection(db_session)
    v1 = await add_doc(db_session, "mv-lin-1", collection_id=source.id)
    await add_doc(db_session, "mv-lin-2", collection_id=source.id, lineage_id=v1.id, version_number=2,
                  lifecycle_state="pending", status="EMBEDDING", file_hash="p" * 64)
    v1_id = v1.id
    await db_session.commit()

    result = await _move(db_session, [v1_id], target)

    assert result.results[0].status == "skipped" and "v2" in result.results[0].detail
    assert str(await _collection_of(db_session, v1_id)) == str(source.id)
    assert pushed == []
