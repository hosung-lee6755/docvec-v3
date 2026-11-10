"""Summary Index — 메타 정보 생성 설계서(2026-07-23) Phase 5.

문서 전체 요약 하나당 벡터 하나를 별도 Qdrant 컬렉션(document_summaries)에
저장해, 청크 단위가 아니라 "이 요약과 가장 가까운 문서가 뭔지"를 찾는 문서
레벨 검색 단위로 쓴다. 기존 청크 컬렉션(qdrant_collection_name)과는 완전히
독립적 — 청크 재처리/삭제와 무관하게 문서당 요약 포인트 하나만 유지한다.
문서 id를 그대로 포인트 id로 재사용해(청크처럼 별도 uuid 불필요) 재요약 시
같은 id로 덮어써 멱등하게 동작한다.
"""
from app.services.embedding import get_embedding_provider
from app.services.qdrant_service import qdrant_service

SUMMARY_COLLECTION_NAME = "document_summaries"


def index_document_summary(
    document_id: str,
    summary: str,
    embedding_model: str | None = None,
    access_fields: dict | None = None,
) -> None:
    """문서 요약이 확정될 때(summary_status → DONE) 호출한다. 빈 요약은
    조용히 무시 — 색인할 내용이 없다.

    access_fields: v3 권한 사본(access_payload.access_payload_sync 결과 —
    sec_rank/acl/owner_id/collection_id). 없으면 권한 필터에 걸려 검색되지 않는다
    (fail-closed). 호출부는 반드시 넘긴다.
    """
    if not summary or not summary.strip():
        return
    provider = get_embedding_provider(embedding_model)
    vector = provider.embed([summary])[0]
    qdrant_service.init_collection(SUMMARY_COLLECTION_NAME, provider.dimension)
    qdrant_service.upsert_points(SUMMARY_COLLECTION_NAME, [{
        "id": document_id,
        "vector": vector,
        "payload": {"document_id": document_id, "summary": summary, **(access_fields or {})},
    }])


def delete_document_summary(document_id: str) -> None:
    """문서 삭제 시 요약 포인트도 함께 제거 — 청크 삭제(delete_by_document)와
    나란히 호출된다."""
    qdrant_service.delete_points(SUMMARY_COLLECTION_NAME, [document_id])


def search_document_summaries(query: str, limit: int = 10, query_filter=None) -> list[dict]:
    """쿼리를 임베딩해 document_summaries 컬렉션에서 가장 가까운 문서 요약
    top-k를 반환한다. query_filter에 v3 권한 필터(access_policy.qdrant_access_filter)를
    넘기면 검색 단계에서 거른다 — 그래도 호출자는 반환된 document_id를 Postgres
    기준으로 다시 확인해야 한다(페이로드 동기화 지연 대비)."""
    provider = get_embedding_provider()
    vector = provider.embed([query])[0]
    return qdrant_service.search(
        SUMMARY_COLLECTION_NAME, vector, limit=limit, query_filter=query_filter
    )
