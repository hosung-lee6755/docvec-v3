"""권한 변경 후 Qdrant 권한 사본 동기화 — API 공통 처리.

Postgres 저장은 이미 끝난 상태에서 호출한다. 동기화가 실패해도 검색 결과는 LLM 투입 전에
Postgres 기준으로 다시 확인되므로 누출은 없다(access_payload 모듈 docstring 참고). 다만
색인된 문서의 사본이 낡으면 원래 보여야 할 문서가 검색에서 빠질 수 있으므로, 사용자가
재시도할 수 있게 502로 알린다(재시도는 멱등). 아직 색인 전인 문서는 색인 시점에 최신
권한이 실리므로 기록만 한다 — metadata._sync_tags_to_index와 같은 규칙.
"""
from collections.abc import Iterable

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.document import Document
from app.services.access_payload import sync_document_access


async def sync_access_or_502(db: AsyncSession, document_ids: Iterable, what: str) -> None:
    ids = [str(d) for d in document_ids]
    if not ids:
        return
    failed = await sync_document_access(db, ids)
    if not failed:
        return
    indexed_failed = (
        await db.scalars(
            select(Document.id).where(Document.id.in_(failed), Document.status == "INDEXED")
        )
    ).all()
    if indexed_failed:
        raise HTTPException(
            status_code=502,
            detail=(
                f"{what}은(는) 저장되었지만 문서 {len(indexed_failed)}건의 검색 인덱스에 "
                "반영하지 못했습니다. 잠시 후 다시 시도하세요."
            ),
        )
