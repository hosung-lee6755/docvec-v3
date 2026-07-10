import logging

from app.core.config import settings
from app.pipeline.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="tasks.update_chunk_text", queue="high", bind=True, max_retries=1)
def update_chunk_text(self, document_id: str, point_id: str, new_text: str) -> dict:
    """Re-embeds a single edited chunk and upserts it under the same point id,
    preserving the rest of the payload. Runs on the worker because the
    embedding model is resident there — the API process must never load it."""
    from app.services.embedding import get_embedding_provider
    from app.services.qdrant_service import qdrant_service

    existing = qdrant_service.get_point(settings.qdrant_collection_name, point_id)
    if existing is None or existing["payload"].get("document_id") != document_id:
        return {"status": "NOT_FOUND", "point_id": point_id}

    provider = get_embedding_provider()
    vector = provider.embed([new_text])[0]

    payload = {**existing["payload"], "text": new_text, "edited": True}
    qdrant_service.upsert_points(
        settings.qdrant_collection_name,
        [{"id": point_id, "vector": vector, "payload": payload}],
    )
    return {"status": "OK", "point_id": point_id}
