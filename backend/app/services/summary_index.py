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
    document_id: str, summary: str, embedding_model: str | None = None,
) -> None:
    """문서 요약이 확정될 때(summary_status → DONE) 호출한다. 빈 요약은
    조용히 무시 — 색인할 내용이 없다."""
    if not summary or not summary.strip():
        return
    provider = get_embedding_provider(embedding_model)
    vector = provider.embed([summary])[0]
    qdrant_service.init_collection(SUMMARY_COLLECTION_NAME, provider.dimension)
    qdrant_service.upsert_points(SUMMARY_COLLECTION_NAME, [{
        "id": document_id,
        "vector": vector,
        "payload": {"document_id": document_id, "summary": summary},
    }])


def delete_document_summary(document_id: str) -> None:
    """문서 삭제 시 요약 포인트도 함께 제거 — 청크 삭제(delete_by_document)와
    나란히 호출된다."""
    qdrant_service.delete_points(SUMMARY_COLLECTION_NAME, [document_id])


def search_document_summaries(query: str, limit: int = 10) -> list[dict]:
    """쿼리를 임베딩해 document_summaries 컬렉션에서 가장 가까운 문서 요약
    top-k를 반환한다. `qdrant_service.search`의 collection_id/필터는 쓰지
    않는다 — 요약 인덱스는 아직 컬렉션 스코프 payload를 싣지 않으므로
    호출자가 반환된 document_id로 접근 권한을 직접 확인해야 한다."""
    provider = get_embedding_provider()
    vector = provider.embed([query])[0]
    return qdrant_service.search(SUMMARY_COLLECTION_NAME, vector, limit=limit)
