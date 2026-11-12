from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchAny,
    MatchValue,
    PayloadSchemaType,
    PointStruct,
    VectorParams,
)

from app.core.config import settings


class QdrantService:
    def __init__(self) -> None:
        self._client = QdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)

    def init_collection(self, name: str, dimension: int) -> None:
        existing = {c.name for c in self._client.get_collections().collections}
        if name not in existing:
            self._client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(size=dimension, distance=Distance.COSINE),
            )
            self.ensure_access_indexes(name)

    def collection_exists(self, name: str) -> bool:
        return name in {c.name for c in self._client.get_collections().collections}

    # v3 권한 필터(access_policy.qdrant_access_filter)가 매 검색에 쓰는 필드. 인덱스가
    # 없어도 결과는 같지만 포인트가 많아지면 필터가 전수 검사로 느려진다. 이미 있는
    # 인덱스를 다시 만들어도 Qdrant는 오류 없이 넘어간다(멱등) — 기존 컬렉션은 백필
    # 스크립트가 이 함수를 호출해 인덱스를 만든다.
    _ACCESS_INDEX_FIELDS = {
        "collection_id": PayloadSchemaType.KEYWORD,
        "document_id": PayloadSchemaType.KEYWORD,
        "owner_id": PayloadSchemaType.KEYWORD,
        "acl": PayloadSchemaType.KEYWORD,
        "sec_rank": PayloadSchemaType.INTEGER,
        # v3 마일스톤 7: 이전 버전·보관·만료 문서의 포인트(inactive)를 검색에서 뺀다
        "lifecycle": PayloadSchemaType.KEYWORD,
    }

    def ensure_access_indexes(self, name: str) -> None:
        for field, schema in self._ACCESS_INDEX_FIELDS.items():
            self._client.create_payload_index(
                collection_name=name, field_name=field, field_schema=schema
            )

    def upsert_points(self, collection: str, points: list[dict]) -> None:
        qdrant_points = [
            PointStruct(
                id=p["id"],
                vector=p["vector"],
                payload=p.get("payload", {}),
            )
            for p in points
        ]
        if qdrant_points:
            self._client.upsert(collection_name=collection, points=qdrant_points)

    def search(
        self,
        collection: str,
        vector: list[float],
        limit: int = 10,
        collection_id: str | None = None,
        collection_ids: list[str] | None = None,
        filters: dict | None = None,
        with_vectors: bool = False,
        query_filter: Filter | None = None,
    ) -> list[dict]:
        """query_filter를 주면 아래 collection_id/filters 조합 대신 그 필터를 그대로 쓴다 —
        v3 권한 필터(access_policy.qdrant_access_filter)를 받는 통로. 사용자 권한이 걸린
        검색 경로는 반드시 이 인자를 써야 한다."""
        if query_filter is not None:
            return self._query(collection, vector, limit, query_filter, with_vectors)
        must_conditions: list[FieldCondition] = []
        if collection_id:
            must_conditions.append(
                FieldCondition(key="collection_id", match=MatchValue(value=collection_id))
            )
        elif collection_ids is not None:
            # Caller has no single collection in mind (e.g. "search all my documents") —
            # restrict to their accessible collections rather than searching the whole
            # shared physical Qdrant collection, which would span every user's data.
            must_conditions.append(
                FieldCondition(key="collection_id", match=MatchAny(any=collection_ids))
            )
        if filters:
            for key, value in filters.items():
                must_conditions.append(
                    FieldCondition(key=key, match=MatchValue(value=value))
                )
        # Chunks disabled from the chunk browser ("검색 제외") are filtered out of
        # every retrieval path (search page + chat RAG) here at the source.
        query_filter = Filter(
            must=must_conditions or None,
            must_not=[FieldCondition(key="disabled", match=MatchValue(value=True))],
        )
        return self._query(collection, vector, limit, query_filter, with_vectors)

    def _query(
        self,
        collection: str,
        vector: list[float],
        limit: int,
        query_filter: Filter,
        with_vectors: bool,
    ) -> list[dict]:
        response = self._client.query_points(
            collection_name=collection,
            query=vector,
            limit=limit,
            query_filter=query_filter,
            with_payload=True,
            with_vectors=with_vectors,
        )
        return [
            {
                "id": str(r.id),
                "score": r.score,
                "payload": r.payload or {},
                **({"vector": r.vector} if with_vectors else {}),
            }
            for r in response.points
        ]

    def get_point(self, collection: str, point_id: str) -> dict | None:
        points = self._client.retrieve(
            collection_name=collection, ids=[point_id], with_payload=True, with_vectors=False
        )
        if not points:
            return None
        return {"id": str(points[0].id), "payload": points[0].payload or {}}

    def set_point_payload(self, collection: str, point_id: str, payload: dict) -> None:
        """Merge the given keys into an existing point's payload (Qdrant
        set_payload semantics — other keys are left untouched)."""
        self._client.set_payload(
            collection_name=collection, payload=payload, points=[point_id]
        )

    def delete_points(self, collection: str, point_ids: list[str]) -> None:
        if point_ids:
            self._client.delete(collection_name=collection, points_selector=point_ids)

    def set_payload_by_document(self, collection: str, document_id: str, payload: dict) -> None:
        """Merge payload keys into every point of a document — used to push
        tag changes to already-indexed chunks without re-embedding."""
        self._client.set_payload(
            collection_name=collection,
            payload=payload,
            points=Filter(
                must=[FieldCondition(key="document_id", match=MatchValue(value=document_id))]
            ),
        )

    def delete_by_document(self, collection: str, document_id: str) -> None:
        self._client.delete(
            collection_name=collection,
            points_selector=Filter(
                must=[FieldCondition(key="document_id", match=MatchValue(value=document_id))]
            ),
        )

    def count_by_collection(self, collection: str, collection_id: str) -> int:
        """Live count of searchable (non-disabled) vectors for a collection --
        backs the embedding-status summary, not a cached/derived number."""
        result = self._client.count(
            collection_name=collection,
            count_filter=Filter(
                must=[FieldCondition(key="collection_id", match=MatchValue(value=collection_id))],
                must_not=[FieldCondition(key="disabled", match=MatchValue(value=True))],
            ),
            exact=True,
        )
        return result.count

    def scroll_by_document(self, document_id: str, limit: int = 10000) -> list[dict]:
        points, _ = self._client.scroll(
            collection_name=settings.qdrant_collection_name,
            scroll_filter=Filter(
                must=[FieldCondition(key="document_id", match=MatchValue(value=document_id))]
            ),
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
        return [{"id": str(p.id), "payload": p.payload or {}} for p in points]


qdrant_service = QdrantService()
