"""업로드 실패 경로 회귀 테스트 — 실제 DB, 스토리지/워커는 가짜.

- 처리 시작이 실패하면 문서가 QUEUED로 방치되지 않고 FAILED + 사유가 기록된다.
- 본문이 상한을 넘으면 메모리에 다 읽기 전에 413으로 거부한다.
"""
import io
from uuid import uuid4

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy import select

from app.api.v1.endpoints import documents as documents_api
from app.api.v1.endpoints.documents import upload as upload_api
from app.db.models.document import Document
from app.db.models.user import User
from tests.unit.test_documents_storage_release import OWNER_ID, db_session  # noqa: F401


class FakeStorage:
    def __init__(self) -> None:
        self.uploaded: list[str] = []
        self.deleted: list[str] = []

    def upload_file(self, bucket, key, content, content_type) -> None:
        self.uploaded.append(key)

    def delete_file(self, bucket, key) -> None:
        self.deleted.append(key)


@pytest.fixture
def storage(monkeypatch):
    fake = FakeStorage()
    monkeypatch.setattr("app.services.storage.storage_service", fake)
    return fake


def _upload(name: str, content: bytes) -> UploadFile:
    return UploadFile(file=io.BytesIO(content), filename=name)


async def _owner(db_session) -> User:
    return await db_session.get(User, OWNER_ID)


@pytest.mark.asyncio
async def test_workflow_start_failure_marks_document_failed(db_session, storage, monkeypatch):
    async def boom(*args, **kwargs):
        raise HTTPException(status_code=500, detail="표준 전처리 워크플로우가 설정되어 있지 않습니다")

    monkeypatch.setattr(upload_api, "_start_preprocess_workflow", boom)

    with pytest.raises(HTTPException) as caught:
        await documents_api.upload_document(
            file=_upload("a.pdf", b"%PDF-1.4 hello"), collection_id=None, skip_review=False,
            workflow_version_id=None, db=db_session, current_user=await _owner(db_session),
        )

    assert caught.value.status_code == 500
    doc = (await db_session.scalars(select(Document).where(Document.created_by == OWNER_ID))).one()
    assert doc.status == "FAILED"
    assert "표준 전처리" in doc.error_message
    assert storage.deleted == []  # 문서는 남기므로 원본도 남긴다(사용자가 삭제 시 정리)


@pytest.mark.asyncio
async def test_oversized_upload_is_rejected_with_413_before_storing(db_session, storage, monkeypatch):
    monkeypatch.setattr(upload_api.settings, "max_upload_size_bytes", 10)

    with pytest.raises(HTTPException) as caught:
        await documents_api.upload_document(
            file=_upload("a.pdf", b"x" * 11), collection_id=None, skip_review=False,
            workflow_version_id=None, db=db_session, current_user=await _owner(db_session),
        )

    assert caught.value.status_code == 413
    assert storage.uploaded == []


@pytest.mark.asyncio
async def test_oversized_zip_archive_is_rejected_with_413(db_session, storage, monkeypatch):
    monkeypatch.setattr(upload_api, "_ZIP_MAX_ARCHIVE_BYTES", 10)

    with pytest.raises(HTTPException) as caught:
        await documents_api.upload_documents_zip(
            file=_upload("b.zip", b"PK" + b"x" * 20), collection_id=None, skip_review=False,
            workflow_version_id=None, db=db_session, current_user=await _owner(db_session),
        )

    assert caught.value.status_code == 413
