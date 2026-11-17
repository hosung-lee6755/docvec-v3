"""보안등급별 외부 모델 차단(전체 점검 2-11, 2026-11-16).

클라우드 모델(OpenAI, Anthropic)을 쓰면 문서 내용이 회사 밖으로 나간다. 예전에는 API 키만 등록돼
있으면 등급과 상관없이 보냈다. 이제 설정한 등급(EXTERNAL_MODEL_MAX_SECURITY_LEVEL, 기본 Internal)을
넘는 문서는 외부 모델로 보내지 않는다. 대상은 세 곳이다.

- 답변 생성: 근거에 넘는 등급의 문서가 있으면 외부 모델로 답하지 않고, 로컬 모델을 고르라고 알린다.
- 답변 검증: 넘는 등급의 근거가 있으면 클라우드 검증 모델 대신 답변을 만든 로컬 모델로 검증한다.
- 그림과 스캔 인식: 넘는 등급의 문서는 클라우드 VLM 대신 로컬 OCR로 읽는다.

문서의 등급은 검색 권한과 같은 방식으로 정한다. 문서에 등급이 없으면 컬렉션의 기본 등급을, 그것도
없으면 시스템 기본 등급을 쓴다(access_policy.effective_level_rank). 알 수 없는 값은 가장 높은 등급으로 본다.
"""
from uuid import UUID

from app.core.config import settings
from app.services.access_policy import SECURITY_LEVELS, document_level_rank

EXTERNAL_BACKENDS = frozenset({"openai", "anthropic"})


class ExternalModelBlockedError(ValueError):
    """외부 모델로 보낼 수 없는 등급의 문서가 근거에 있다. 메시지는 사용자에게 그대로 보인다."""


def is_external_backend(backend: str | None) -> bool:
    return backend in EXTERNAL_BACKENDS


def _max_rank() -> int:
    level = settings.external_model_max_security_level
    # 설정값이 잘못됐으면 아무 등급도 내보내지 않는다(fail-closed)
    return SECURITY_LEVELS.index(level) if level in SECURITY_LEVELS else -1


def allows_external(security_level: str | None, collection_default_level: str | None = None) -> bool:
    return document_level_rank(security_level or collection_default_level) <= _max_rank()


def document_allows_external(db, document) -> bool:
    """문서 하나를 외부 모델로 보내도 되는가(그림과 스캔 인식용)."""
    from app.db.models.collection import Collection

    default_level = None
    if document.collection_id:
        collection = db.get(Collection, document.collection_id)
        default_level = collection.default_security_level if collection else None
    return allows_external(document.security_level, default_level)


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return False
    return True


def blocked_document_ids(db, document_ids) -> list[str]:
    """외부 모델로 보낼 수 없는 문서의 id. 지워졌거나 찾지 못한 문서도 보낼 수 없는 것으로 본다."""
    from app.db.models.collection import Collection
    from app.db.models.document import Document

    wanted = {str(i) for i in document_ids if i}
    # id 모양이 아닌 값으로 조회하면 DB 오류가 나서 트랜잭션이 깨진다. 그런 값은 찾지 못한 문서로 둔다
    valid = [i for i in wanted if _is_uuid(i)]
    if not valid:
        return sorted(wanted)
    rows = (
        db.query(Document.id, Document.security_level, Collection.default_security_level)
        .outerjoin(Collection, Collection.id == Document.collection_id)
        .filter(Document.id.in_(valid))
        .all()
    )
    allowed = {str(doc_id) for doc_id, level, default_level in rows if allows_external(level, default_level)}
    return sorted(wanted - allowed)


def ensure_external_allowed(db, chunks: list[dict]) -> None:
    """근거 청크를 외부 모델로 보내도 되는지 확인한다. 안 되면 ExternalModelBlockedError를 낸다."""
    if blocked_document_ids(db, [c.get("document_id") for c in chunks]):
        raise ExternalModelBlockedError(
            f"근거 문서 가운데 보안등급이 {settings.external_model_max_security_level}보다 높은 문서가 있어 "
            "외부 모델로 답변을 만들 수 없습니다. 로컬 모델을 선택해 다시 질문하세요."
        )
