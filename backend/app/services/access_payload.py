"""문서 권한 페이로드(Qdrant 사본) 계산·동기화 — 규칙은 access_policy가 정한다.

Postgres가 정본이고, 이 모듈은 그 판정 재료를 Qdrant 포인트(본문 청크 + 요약)에 복사한다.
복사가 늦거나 실패해도 검색 결과는 LLM 투입 전에 Postgres로 다시 확인되므로 누출되지
않는다(fail-closed). 권한 필드가 없는 포인트는 검색 필터에 걸리지 않아 보이지 않는다 —
그래서 v3 배포 시 scripts/backfill_access_payload.py로 기존 포인트를 한 번 채워야 한다.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable

from app.core.config import settings
from app.services.access_policy import (
    DocumentAccessFacts,
    document_access_payload,
    load_document_facts,
    load_document_facts_sync,
)

logger = logging.getLogger(__name__)

# 문서가 사라졌는데 포인트가 남은 경우 등 판정 재료가 없을 때 쓰는 값 — 아무도 매칭되지
# 않는 ACL이라 소유자 조건 외에는 검색되지 않는다.
_DENY_ALL_PAYLOAD = {"sec_rank": 2, "acl": ["!none"], "owner_id": None, "collection_id": None}


def point_access_payload(facts: DocumentAccessFacts | None) -> dict:
    """포인트에 병합할 권한 필드(+ collection_id)."""
    if facts is None:
        return dict(_DENY_ALL_PAYLOAD)
    return {**document_access_payload(facts), "collection_id": facts.collection_id}


def access_payload_sync(db, document_id: str) -> dict:
    """색인 시점(워커, sync 세션)에 포인트 페이로드에 병합할 권한 필드."""
    facts = load_document_facts_sync(db, [str(document_id)])
    return point_access_payload(facts.get(str(document_id)))


def _push_payload(document_id: str, payload: dict) -> None:
    from app.services.qdrant_service import qdrant_service
    from app.services.summary_index import SUMMARY_COLLECTION_NAME

    qdrant_service.set_payload_by_document(settings.qdrant_collection_name, document_id, payload)
    # 요약 포인트는 문서 id를 포인트 id로 쓴다. 요약이 없거나 요약 컬렉션이 아직 없으면
    # 덮어쓸 대상이 없으니 건너뛴다.
    if qdrant_service.collection_exists(SUMMARY_COLLECTION_NAME):
        qdrant_service.set_payload_by_document(SUMMARY_COLLECTION_NAME, document_id, payload)


def sync_document_access_sync(db, document_ids: Iterable[str]) -> list[str]:
    """권한이 바뀐 문서들의 포인트 페이로드를 갱신한다. 실패한 문서 id 목록을 돌려준다."""
    ids = [str(d) for d in document_ids]
    facts = load_document_facts_sync(db, ids)
    failed: list[str] = []
    for doc_id in ids:
        try:
            _push_payload(doc_id, point_access_payload(facts.get(doc_id)))
        except Exception:
            logger.warning("access payload sync failed: document=%s", doc_id, exc_info=True)
            failed.append(doc_id)
    return failed


async def sync_document_access(db, document_ids: Iterable[str]) -> list[str]:
    """API(async 세션)용 — Qdrant 호출은 스레드로 넘긴다. 실패한 문서 id 목록을 돌려준다."""
    ids = [str(d) for d in document_ids]
    facts = await load_document_facts(db, ids)
    failed: list[str] = []
    for doc_id in ids:
        try:
            await asyncio.to_thread(_push_payload, doc_id, point_access_payload(facts.get(doc_id)))
        except Exception:
            logger.warning("access payload sync failed: document=%s", doc_id, exc_info=True)
            failed.append(doc_id)
    return failed


def backfill_access_payloads(db, *, dry_run: bool = False, batch_size: int = 200) -> dict:
    """v3 배포 시 1회 실행 — 기존 포인트(본문·요약)에 권한 사본을 채운다. 재임베딩 없음.

    멱등이다: 매번 Postgres 정본에서 다시 계산해 덮어쓴다. 권한 필드 인덱스도 함께 만든다.
    dry_run이면 대상 문서 수만 세고 Qdrant를 건드리지 않는다.
    """
    from sqlalchemy import select

    from app.db.models.document import Document
    from app.services.qdrant_service import qdrant_service
    from app.services.summary_index import SUMMARY_COLLECTION_NAME

    collections = [settings.qdrant_collection_name]
    if qdrant_service.collection_exists(SUMMARY_COLLECTION_NAME):
        collections.append(SUMMARY_COLLECTION_NAME)

    doc_ids = [str(d) for d in db.scalars(select(Document.id).order_by(Document.id)).all()]
    stats = {"documents": len(doc_ids), "synced": 0, "failed": [], "collections": collections}
    if dry_run:
        return stats

    for name in collections:
        qdrant_service.ensure_access_indexes(name)
    for start in range(0, len(doc_ids), batch_size):
        batch = doc_ids[start:start + batch_size]
        failed = sync_document_access_sync(db, batch)
        stats["failed"].extend(failed)
        stats["synced"] += len(batch) - len(failed)
        logger.info("access payload backfill: %d/%d", start + len(batch), len(doc_ids))
    return stats
