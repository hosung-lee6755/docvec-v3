"""문서 원본 파일(MinIO) 삭제 헬퍼.

기존 문서는 `{sha256}/{파일명}` 키를 같은 내용의 문서끼리 공유한다(신규 업로드는 문서 id를
키에 포함해 공유하지 않는다). 그래서 문서를 지울 때 같은 키를 다른 문서가 아직 참조하면
객체를 남겨 둬야 한다. 모든 삭제 경로(단일/일괄/컬렉션)가 이 함수를 거친다.
"""
import asyncio
import logging
from collections.abc import Iterable
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.document import Document

logger = logging.getLogger(__name__)


class _Storage(Protocol):
    def delete_file(self, bucket: str, key: str) -> None: ...


async def release_original(
    db: AsyncSession,
    storage: _Storage,
    bucket: str,
    minio_key: str,
    exclude_document_ids: Iterable[str] | None = None,
) -> bool:
    """다른 문서가 `minio_key`를 참조하지 않을 때만 객체를 지운다.

    `exclude_document_ids`는 같은 작업에서 함께 삭제되는(아직 커밋 전일 수 있는) 문서로,
    참조로 세지 않는다. 객체를 실제로 지웠으면 True, 참조가 남아 있거나 삭제에
    실패하면 False. 스토리지 오류는 삭제 흐름을 깨지 않도록 기록만 한다.
    """
    query = select(func.count()).select_from(Document).where(Document.minio_key == minio_key)
    excluded = [str(doc_id) for doc_id in (exclude_document_ids or [])]
    if excluded:
        query = query.where(Document.id.not_in(excluded))
    if await db.scalar(query):
        return False
    try:
        await asyncio.to_thread(storage.delete_file, bucket, minio_key)
    except Exception:
        logger.warning("원본 파일 삭제 실패: %s", minio_key, exc_info=True)
        return False
    return True
