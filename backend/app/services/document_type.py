"""문서 유형(2026-11-27, 문서유형별_처리_방안_검토).

유형에 따라 구조 분석과 청크 분할이 달라진다. 지금은 규정·법령만 다르게 처리한다(조 단위 제목과 청크).
어떤 유형을 쓸지는 다음 순서로 정한다.

1. 사용자가 문서에 지정한 유형(업로드 때 고르거나 문서 화면에서 바꾼 값)
2. 문서가 든 컬렉션의 기본 유형
3. 구조 분석이 본문에서 판별한 유형(조 제목이 여러 개 이어지면 규정)
"""
from typing import Literal

REGULATION = "regulation"
GENERAL = "general"
DOCUMENT_TYPES: tuple[str, ...] = (REGULATION, GENERAL)
DOCUMENT_TYPE_LABELS: dict[str, str] = {REGULATION: "규정·법령", GENERAL: "일반 문서"}
# API 입력 검증용. DOCUMENT_TYPES 와 같은 값을 둔다
DocumentType = Literal["regulation", "general"]


def normalize_document_type(value: str | None) -> str | None:
    """입력값을 저장할 유형으로 바꾼다. 빈 값과 "auto" 는 자동 판별(None)이다. 모르는 값이면 ValueError."""
    cleaned = (value or "").strip().lower()
    if cleaned in ("", "auto"):
        return None
    if cleaned not in DOCUMENT_TYPES:
        raise ValueError(f"알 수 없는 문서 유형입니다: {value}. 가능한 값은 auto, {', '.join(DOCUMENT_TYPES)} 입니다.")
    return cleaned


def chosen_document_type(document_type: str | None, collection_default: str | None) -> str | None:
    """사용자가 정한 유형(문서 지정값, 없으면 컬렉션 기본값). 둘 다 없으면 None(자동 판별)."""
    return document_type or collection_default or None


def collection_default_type(db, doc) -> str | None:
    """문서가 든 컬렉션의 기본 유형(동기 세션, 파이프라인 블록용). 컬렉션이 없으면 None."""
    from app.db.models.collection import Collection

    collection_id = getattr(doc, "collection_id", None)
    if not collection_id:
        return None
    value = db.query(Collection.default_document_type).filter(Collection.id == collection_id).scalar()
    return value if isinstance(value, str) else None


def effective_document_type(
    document_type: str | None, collection_default: str | None, detected: str | None,
) -> str:
    """처리에 쓸 유형. 지정값과 컬렉션 기본값이 없으면 판별값, 그것도 없으면 일반 문서."""
    return chosen_document_type(document_type, collection_default) or detected or GENERAL
