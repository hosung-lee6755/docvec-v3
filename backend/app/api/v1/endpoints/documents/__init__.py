"""문서 API 라우터 — 기능별 모듈을 원래 선언 순서 그대로 하나의 router로 합친다.

순서가 중요하다: 정적 경로(`/tags`, `/batch`)는 `/{document_id}` 경로보다 먼저 등록돼야
path 변수로 잡히지 않는다. 각 모듈은 자신이 맡은 구간의 라우트만 선언한다.
"""
from fastapi import APIRouter

from app.api.v1.endpoints.documents import (
    chunks,
    listing,
    metadata,
    processing,
    structure,
    upload,
)

router = APIRouter()
for _module in (upload, listing, processing, structure, chunks, metadata):
    # include_router는 경로가 ""인 목록 라우트를 거부하므로 선언 순서 그대로 라우트를 이어붙인다.
    router.routes.extend(_module.router.routes)

# 기존 import 경로(`from app.api.v1.endpoints.documents import X`) 호환용 재노출.
from app.api.v1.endpoints.documents.chunks import (  # noqa: E402,F401
    delete_document_chunk,
    restore_document_revision,
    retry_failed_document,
    update_document_chunk,
)
from app.api.v1.endpoints.documents.listing import (  # noqa: E402,F401
    batch_delete_documents,
    batch_reprocess_documents,
    delete_document,
    list_documents,
)
from app.api.v1.endpoints.documents.metadata import (  # noqa: E402,F401
    accept_tag_suggestion,
    dismiss_tag_suggestion,
    update_document_tags,
)
from app.api.v1.endpoints.documents.models import (  # noqa: E402,F401
    BatchDeleteRequest,
    BatchReprocessRequest,
)
from app.api.v1.endpoints.documents.processing import proceed_document, reprocess_document  # noqa: E402,F401
from app.api.v1.endpoints.documents.structure import _resolve_cleaning_rule_name  # noqa: E402,F401
from app.api.v1.endpoints.documents.upload import (  # noqa: E402,F401
    _SUPPORTED_UPLOAD_SUFFIXES,
    _ZIP_MAX_ENTRIES,
    upload_document,
    upload_documents_zip,
)
