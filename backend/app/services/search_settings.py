"""컬렉션별 검색 설정(v3 마일스톤 6).

컬렉션 편집자가 정한 검색 방식을 그 컬렉션의 검색 화면과 채팅이 함께 따른다. 저장은
`collections.search_settings`(JSON)이고, null이거나 읽을 수 없으면 기본값이다. 기본값은
마일스톤 6 이전의 채팅 동작(하이브리드, 근거 5건, 재순위 켬)과 같다.
"""
import logging
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

logger = logging.getLogger(__name__)

MIN_TOP_K = 3
MAX_TOP_K = 10


class SearchSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    # hybrid: 벡터 유사도와 키워드(BM25)를 섞는다. vector: 벡터 유사도만 쓴다
    mode: Literal["hybrid", "vector"] = "hybrid"
    # 채팅에 근거로 넣는 발췌문 수. 검색 화면에서는 결과 수의 기본값이 아니다(화면이 따로 정한다)
    top_k: int = Field(5, ge=MIN_TOP_K, le=MAX_TOP_K)
    # 교차 인코더 재순위. 끄면 빠르지만 근거의 정확도가 떨어질 수 있다
    rerank: bool = True
    # MMR로 비슷한 발췌문을 덜 뽑는다
    diversify: bool = False
    # 하이브리드에서 벡터 점수의 비중. 나머지가 키워드 점수의 비중이다
    vector_weight: float = Field(0.6, ge=0.1, le=0.9)


DEFAULT_SEARCH_SETTINGS = SearchSettings()


def resolve_search_settings(raw: dict | None) -> SearchSettings:
    """저장된 JSON을 설정으로 읽는다. 비었거나 형식이 틀리면 기본값을 쓴다(검색이 멈추지 않게)."""
    if not raw:
        return DEFAULT_SEARCH_SETTINGS
    try:
        return SearchSettings(**raw)
    except (TypeError, ValidationError):
        logger.warning("invalid collection search_settings; using defaults", extra={"raw": raw})
        return DEFAULT_SEARCH_SETTINGS


def collection_search_settings_sync(db, collection_id: str | None) -> SearchSettings:
    """채팅 워커용. 범위가 컬렉션 하나일 때만 그 설정을 쓰고, 아니면 기본값이다."""
    if not collection_id:
        return DEFAULT_SEARCH_SETTINGS
    from app.db.models.collection import Collection

    collection = db.get(Collection, collection_id)
    return resolve_search_settings(collection.search_settings if collection else None)


async def stored_collection_search_settings(db, collection_id) -> SearchSettings | None:
    """컬렉션에 저장한 설정. 저장한 적이 없으면 None이다(검색 API의 예전 기본값을 지키는 데 쓴다)."""
    if not collection_id:
        return None
    from app.db.models.collection import Collection

    collection = await db.get(Collection, collection_id)
    if collection is None or not collection.search_settings:
        return None
    return resolve_search_settings(collection.search_settings)
