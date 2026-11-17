import logging

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    HasIdCondition,
    MatchAny,
    MatchValue,
    Modifier,
    PayloadSchemaType,
    PointStruct,
    SparseVector,
    SparseVectorParams,
    VectorParams,
)

from app.core.config import settings

logger = logging.getLogger(__name__)

# 키워드 색인(services/lexical_index.py)은 청크 컬렉션 옆의 보조 컬렉션에 둔다. 이미 만든 컬렉션에는
# sparse 벡터를 나중에 추가할 수 없기 때문이다(Qdrant 1.18에서 확인). 점 id는 청크 컬렉션과 같다.
# 보조 컬렉션은 후보 id만 알려 주고, 권한 필터와 본문은 항상 청크 컬렉션에서 다시 확인한다.
LEXICAL_SUFFIX = "_lex"
LEXICAL_VECTOR = "text"
_LEXICAL_PAYLOAD_FIELDS = ("collection_id", "document_id")


class QdrantService:
    def __init__(self) -> None:
        self._client = QdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)
        self._lexical_ready: set[str] = set()

    # ------------------------------------------------------------------ 키워드 색인

    @staticmethod
    def lexical_name(collection: str) -> str:
        return f"{collection}{LEXICAL_SUFFIX}"

    @staticmethod
    def has_lexical_index(collection: str) -> bool:
        """키워드 색인을 두는 컬렉션인지. 청크 컬렉션만 해당하고 요약 색인 등은 아니다."""
        return collection == settings.qdrant_collection_name

    def ensure_lexical_collection(self, collection: str) -> str:
        name = self.lexical_name(collection)
        if name in self._lexical_ready:
            return name
        if not self._client.collection_exists(name):
            self._client.create_collection(
                collection_name=name,
                vectors_config={},
                sparse_vectors_config={LEXICAL_VECTOR: SparseVectorParams(modifier=Modifier.IDF)},
            )
            for field in _LEXICAL_PAYLOAD_FIELDS:
                self._client.create_payload_index(
                    collection_name=name, field_name=field, field_schema=PayloadSchemaType.KEYWORD
                )
        self._lexical_ready.add(name)
        return name

    def upsert_lexical(self, collection: str, points: list[dict]) -> int:
        """청크 점의 색인용 본문(index_text, 없으면 text)으로 키워드 색인을 만든다. 쓴 점의 수를 돌려준다.
        낱말이 하나도 없는 점은 색인에서 지운다(본문을 고쳐 비운 경우)."""
        from app.services.lexical_index import document_vectors

        if not points:
            return 0
        name = self.ensure_lexical_collection(collection)
        texts = [(p.get("payload") or {}).get("index_text") or (p.get("payload") or {}).get("text") or "" for p in points]
        rows, empty_ids = [], []
        for point, (indices, values) in zip(points, document_vectors(texts), strict=True):
            if not indices:
                empty_ids.append(point["id"])
                continue
            payload = point.get("payload") or {}
            rows.append(PointStruct(
                id=point["id"],
                vector={LEXICAL_VECTOR: SparseVector(indices=indices, values=values)},
                payload={field: payload.get(field) for field in _LEXICAL_PAYLOAD_FIELDS},
            ))
        if rows:
            self._client.upsert(collection_name=name, points=rows)
        if empty_ids:
            self._client.delete(collection_name=name, points_selector=empty_ids)
        return len(rows)

    def rebuild_lexical(self, collection: str, batch_size: int = 200) -> dict:
        """청크 컬렉션 전체를 훑어 키워드 색인을 다시 만든다(scripts/backfill_lexical_index.py)."""
        scanned = indexed = 0
        offset = None
        while True:
            points, offset = self._client.scroll(
                collection_name=collection, limit=batch_size, offset=offset,
                with_payload=True, with_vectors=False,
            )
            batch = [{"id": str(p.id), "payload": p.payload or {}} for p in points]
            scanned += len(batch)
            indexed += self.upsert_lexical(collection, batch)
            if offset is None:
                return {"scanned": scanned, "indexed": indexed}

    def _mirror_to_lexical(self, collection: str, action, what: str) -> None:
        """청크 컬렉션에 한 일을 키워드 색인에도 한다. 키워드 색인은 보조라서, 실패해도 청크 색인 작업은
        성공으로 두고 기록만 남긴다. 남은 낡은 점은 검색 때 청크 컬렉션 재조회에서 걸러진다."""
        if not self.has_lexical_index(collection):
            return
        try:
            action(self.lexical_name(collection))
        except Exception:  # noqa: BLE001
            logger.exception("lexical index %s failed: collection=%s", what, collection)

    def lexical_candidate_ids(
        self, collection: str, lexical: tuple[list[int], list[float]], limit: int,
        collection_ids: list[str] | None = None,
    ) -> list[str]:
        """질의 낱말과 겹치는 청크의 점 id(점수 높은 순). 범위는 컬렉션 id로만 좁힌다."""
        indices, values = lexical
        if not indices or not self.has_lexical_index(collection):
            return []
        name = self.lexical_name(collection)
        if name not in self._lexical_ready and not self._client.collection_exists(name):
            return []
        scope = Filter(must=[FieldCondition(key="collection_id", match=MatchAny(any=collection_ids))]) \
            if collection_ids else None
        response = self._client.query_points(
            collection_name=name,
            query=SparseVector(indices=indices, values=values),
            using=LEXICAL_VECTOR,
            limit=limit,
            query_filter=scope,
            with_payload=False,
        )
        return [str(p.id) for p in response.points]

    def _add_lexical_hits(
        self, collection: str, vector: list[float], hits: list[dict], lexical, lexical_scope,
        limit: int, query_filter: Filter, with_vectors: bool,
    ) -> list[dict]:
        """벡터 후보에 없는 키워드 후보를 더한다. 더하는 점은 청크 컬렉션에서 같은 필터로 다시 조회하므로
        권한 밖 문서나 검색 제외 청크는 들어오지 않고, 점수도 벡터 후보와 같은 코사인 유사도다."""
        try:
            known = {h["id"] for h in hits}
            extra = [i for i in self.lexical_candidate_ids(collection, lexical, limit, lexical_scope) if i not in known]
            if not extra:
                return hits
            only_extra = Filter(must=[query_filter, HasIdCondition(has_id=extra)])
            added = self._query(collection, vector, len(extra), only_extra, with_vectors)
        except Exception:  # noqa: BLE001 - 키워드 색인이 고장 나도 벡터 검색 결과는 돌려준다
            logger.exception("lexical candidate lookup failed; using vector candidates only")
            return hits
        return hits + [{**h, "lexical_only": True} for h in added]

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
            self._mirror_to_lexical(collection, lambda _name: self.upsert_lexical(collection, points), "upsert")

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
        lexical: tuple[list[int], list[float]] | None = None,
        lexical_scope: list[str] | None = None,
    ) -> list[dict]:
        """query_filter를 주면 아래 collection_id/filters 조합 대신 그 필터를 그대로 쓴다 —
        v3 권한 필터(access_policy.qdrant_access_filter)를 받는 통로. 사용자 권한이 걸린
        검색 경로는 반드시 이 인자를 써야 한다.
        lexical(질의의 sparse 벡터)을 주면 키워드 색인에서 찾은 후보를 벡터 후보 뒤에 더한다
        (하이브리드 검색). lexical_scope는 그 조회를 좁힐 컬렉션 id 목록이다."""
        if query_filter is not None:
            hits = self._query(collection, vector, limit, query_filter, with_vectors)
            if lexical and lexical[0]:
                return self._add_lexical_hits(
                    collection, vector, hits, lexical, lexical_scope, limit, query_filter, with_vectors
                )
            return hits
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

    def get_points(self, collection: str, point_ids: list[str]) -> list[dict]:
        """여러 점을 id로 한 번에 읽는다(벡터 제외). 없는 id는 결과에서 빠진다."""
        if not point_ids:
            return []
        points = self._client.retrieve(
            collection_name=collection, ids=point_ids, with_payload=True, with_vectors=False
        )
        return [{"id": str(p.id), "payload": p.payload or {}} for p in points]

    def set_point_payload(self, collection: str, point_id: str, payload: dict) -> None:
        """Merge the given keys into an existing point's payload (Qdrant
        set_payload semantics — other keys are left untouched)."""
        self._client.set_payload(
            collection_name=collection, payload=payload, points=[point_id]
        )

    def delete_points(self, collection: str, point_ids: list[str]) -> None:
        if point_ids:
            self._client.delete(collection_name=collection, points_selector=point_ids)
            self._mirror_to_lexical(
                collection, lambda name: self._delete_lexical(name, point_ids), "delete",
            )

    def _delete_lexical(self, name: str, selector) -> None:
        if self._client.collection_exists(name):
            self._client.delete(collection_name=name, points_selector=selector)

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
        selector = Filter(must=[FieldCondition(key="document_id", match=MatchValue(value=document_id))])
        self._client.delete(collection_name=collection, points_selector=selector)
        self._mirror_to_lexical(collection, lambda name: self._delete_lexical(name, selector), "delete")

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
