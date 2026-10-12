"""문서 삭제 엔드포인트(단일/일괄) 회귀 테스트 — 실제 DB, 외부 서비스는 가짜.

다음 결함을 고정한다.
- 삭제가 외부 서비스(Qdrant 컬렉션 없음 등) 실패로 500이 되지 않는다(E2E 재현: 404 → 500).
- 감사 로그가 삭제와 함께 저장된다(`log_audit`는 동기 함수라 await하면 TypeError).
- 같은 원본 키를 다른 문서가 참조하면 원본을 지우지 않는다.
"""
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.api.v1.endpoints import documents as documents_api
from app.db.models.audit_log import AuditLog
from app.db.models.document import Document
from app.db.models.user import User
from tests.unit.test_documents_storage_release import OWNER_ID, _doc, db_session  # noqa: F401


class FakeStorage:
    def __init__(self) -> None:
        self.deleted: list[tuple[str, str]] = []

    def delete_file(self, bucket: str, key: str) -> None:
        self.deleted.append((bucket, key))


class FailingQdrant:
    """document_summaries 컬렉션이 없을 때처럼 모든 호출이 예외를 낸다."""

    def delete_by_document(self, collection: str, document_id: str) -> None:
        raise RuntimeError("Unexpected Response: 404 (Not Found)")


@pytest.fixture
def externals(monkeypatch):
    storage = FakeStorage()

    def failing_summary_delete(document_id: str) -> None:
        raise RuntimeError("Collection `document_summaries` doesn't exist!")

    monkeypatch.setattr("app.services.storage.storage_service", storage)
    monkeypatch.setattr("app.services.qdrant_service.qdrant_service", FailingQdrant())
    monkeypatch.setattr("app.services.summary_index.delete_document_summary", failing_summary_delete)
    return storage


async def _owner(db_session) -> User:
    return await db_session.get(User, OWNER_ID)


async def _exists(db_session, document_id) -> bool:
    """아이덴티티 맵이 아니라 DB에 실제로 행이 남아 있는지 센다."""
    count = await db_session.scalar(
        select(func.count()).select_from(Document).where(Document.id == document_id)
    )
    return bool(count)


@pytest.mark.asyncio
async def test_delete_document_succeeds_and_audits_when_external_cleanup_fails(db_session, externals):
    doc = _doc(f"{uuid4()}/only.pdf")
    db_session.add(doc)
    await db_session.flush()

    result = await documents_api.delete_document(doc.id, db_session, await _owner(db_session))

    assert result == {"message": "Document deleted"}
    assert not await _exists(db_session, doc.id)
    audits =(await db_session.scalars(select(AuditLog).where(AuditLog.resource_id == str(doc.id)))).all()
    assert [a.action for a in audits] == ["document.delete"]
    assert externals.deleted == [("originals", doc.minio_key)]


@pytest.mark.asyncio
async def test_delete_document_keeps_original_still_used_by_another_document(db_session, externals):
    shared = f"{'a' * 64}/shared.docx"
    first, second = _doc(shared), _doc(shared)
    db_session.add_all([first, second])
    await db_session.flush()

    await documents_api.delete_document(first.id, db_session, await _owner(db_session))

    assert externals.deleted == []
    assert not await _exists(db_session, first.id)
    assert await _exists(db_session, second.id)

    await documents_api.delete_document(second.id, db_session, await _owner(db_session))

    assert externals.deleted == [("originals", shared)]


@pytest.mark.asyncio
async def test_batch_delete_removes_documents_audits_each_and_cleans_originals(db_session, externals):
    docs = [_doc(f"{uuid4()}/{n}.pdf") for n in ("a", "b")]
    db_session.add_all(docs)
    await db_session.flush()
    body = documents_api.BatchDeleteRequest(ids=[d.id for d in docs])

    result = await documents_api.batch_delete_documents(body, db_session, await _owner(db_session))

    assert result["deleted"] == 2
    for d in docs:
        assert not await _exists(db_session, d.id)
    audited = {
        a.resource_id
        for a in (await db_session.scalars(select(AuditLog).where(AuditLog.action == "document.delete"))).all()
    }
    assert audited == {str(d.id) for d in docs}
    assert sorted(key for _, key in externals.deleted) == sorted(d.minio_key for d in docs)
