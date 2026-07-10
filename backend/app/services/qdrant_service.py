from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchAny,
    MatchValue,
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
    ) -> list[dict]:
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
        response = self._client.query_points(
            collection_name=collection,
            query=vector,
            limit=limit,
            query_filter=query_filter,
            with_payload=True,
        )
        return [
            {"id": str(r.id), "score": r.score, "payload": r.payload or {}}
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
