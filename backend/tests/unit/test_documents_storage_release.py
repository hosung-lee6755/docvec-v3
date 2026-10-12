"""원본 파일 삭제 시 참조 확인(ref-count) 동작 검증.

과거 업로드는 `{sha256}/{파일명}` 키를 같은 내용의 문서끼리 공유한다. 한 문서를 삭제하면서
다른 문서가 아직 참조하는 원본 객체까지 지우면 그쪽 다운로드/미리보기/재처리가 404가 된다
(E2E에서 컬렉션 A·B에 같은 파일을 올린 뒤 B 삭제 → A 다운로드 404로 재현).
"""
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.db.base import Base
from app.db.models.document import Document
from app.db.models.user import User
from app.services.document_storage import release_original
from tests.conftest import TEST_DATABASE_URL

BUCKET = "originals"
OWNER_ID = str(uuid4())


@pytest_asyncio.fixture
async def db_session():
    """테스트마다 새 엔진/커넥션을 쓰고 트랜잭션을 롤백한다.

    공용 conftest의 세션 범위 엔진은 테스트별 이벤트 루프와 섞여
    'another operation is in progress'로 실패해 쓰지 않는다.
    """
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with engine.connect() as conn:
        transaction = await conn.begin()
        # commit()은 SAVEPOINT 해제, rollback()은 SAVEPOINT까지만 되돌린다 — 실제 커밋/롤백
        # 의미를 흉내 내면서도 테스트 종료 시 바깥 트랜잭션을 롤백해 흔적을 남기지 않는다.
        session = AsyncSession(bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint")
        session.add(
            User(
                id=OWNER_ID,
                email=f"{OWNER_ID}@example.com",
                username="owner",
                hashed_password="!",
                role="viewer",
                is_active=True,
            )
        )
        await session.flush()
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()
    await engine.dispose()


class FakeStorage:
    def __init__(self) -> None:
        self.deleted: list[tuple[str, str]] = []

    def delete_file(self, bucket: str, key: str) -> None:
        self.deleted.append((bucket, key))


def _doc(key: str, **overrides) -> Document:
    fields = dict(
        id=str(uuid4()),
        filename="a.docx",
        original_filename="a.docx",
        file_size=1,
        mime_type="application/octet-stream",
        file_hash="h" * 64,
        minio_key=key,
        status="INDEXED",
        created_by=OWNER_ID,
    )
    fields.update(overrides)
    return Document(**fields)


@pytest.mark.asyncio
async def test_keeps_object_while_another_document_still_references_the_key(db_session):
    shared = f"{'h' * 64}/a.docx"
    db_session.add(_doc(shared))
    await db_session.flush()
    storage = FakeStorage()

    deleted = await release_original(db_session, storage, BUCKET, shared)

    assert deleted is False
    assert storage.deleted == []


@pytest.mark.asyncio
async def test_deletes_object_when_no_document_references_the_key(db_session):
    storage = FakeStorage()

    deleted = await release_original(db_session, storage, BUCKET, "unreferenced/key.pdf")

    assert deleted is True
    assert storage.deleted == [(BUCKET, "unreferenced/key.pdf")]


@pytest.mark.asyncio
async def test_ignores_documents_being_deleted_in_the_same_operation(db_session):
    """컬렉션 삭제처럼 아직 커밋 전인 삭제 대상 문서는 참조로 세지 않는다."""
    key = "shared/b.pdf"
    leaving = _doc(key)
    staying = _doc(key)
    db_session.add_all([leaving, staying])
    await db_session.flush()
    storage = FakeStorage()

    # 한 문서만 삭제 대상이면 다른 문서가 남아 있으므로 지우지 않는다.
    assert await release_original(
        db_session, storage, BUCKET, key, exclude_document_ids=[leaving.id]
    ) is False
    # 두 문서가 모두 삭제 대상이면 객체를 지운다.
    assert await release_original(
        db_session, storage, BUCKET, key, exclude_document_ids=[leaving.id, staying.id]
    ) is True
    assert storage.deleted == [(BUCKET, key)]


@pytest.mark.asyncio
async def test_storage_failure_is_swallowed_and_reported_as_not_deleted(db_session):
    class BrokenStorage:
        def delete_file(self, bucket: str, key: str) -> None:
            raise RuntimeError("minio down")

    deleted = await release_original(db_session, BrokenStorage(), BUCKET, "k/orphan.pdf")

    assert deleted is False
