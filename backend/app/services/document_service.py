from uuid import UUID

from fastapi import HTTPException, status

from app.core.config import settings
from app.services.qdrant_service import QdrantService
from app.services.storage import StorageService


def _get_qdrant() -> QdrantService:
    return QdrantService()


def _get_storage() -> StorageService:
    return StorageService()


_MAX_OVERLAP_CHECK = 500


def _merge_chunks(chunk_texts: list[str]) -> str:
    """Join adjacent chunks, trimming the chunk-overlap region so the shared
    text between consecutive chunks (see process.py's _chunk_text overlap)
    isn't duplicated in the reassembled document."""
    if not chunk_texts:
        return ""
    merged = chunk_texts[0]
    for text in chunk_texts[1:]:
        max_check = min(_MAX_OVERLAP_CHECK, len(merged), len(text))
        overlap_len = 0
        for length in range(max_check, 0, -1):
            if merged[-length:] == text[:length]:
                overlap_len = length
                break
        merged += "\n\n" + text[overlap_len:]
    return merged


def get_document_content(document_id: UUID) -> dict:
    """Assemble full document text from Qdrant chunks sorted by chunk_index."""
    qdrant = _get_qdrant()
    doc_id_str = str(document_id)

    hits = qdrant.scroll_by_document(doc_id_str)
    if not hits:
        return {"document_id": doc_id_str, "chunks": [], "full_text": ""}

    hits.sort(key=lambda h: h["payload"].get("chunk_index", 0))

    chunks = [
        {
            "chunk_index": h["payload"].get("chunk_index", i),
            "text": h["payload"].get("text", ""),
        }
        for i, h in enumerate(hits)
    ]
    full_text = _merge_chunks([c["text"] for c in chunks])

    return {
        "document_id": doc_id_str,
        "chunks": chunks,
        "full_text": full_text,
        "chunk_count": len(chunks),
    }


def get_download_url(minio_key: str, expires_seconds: int = 3600) -> str:
    """Return a presigned MinIO URL for the original file (1h expiry). The URL stays valid
    after access is revoked or the document is deleted, so it is minted per request and
    kept short instead of the previous 24h."""
    storage = _get_storage()
    url = storage.get_presigned_url(
        settings.minio_bucket_originals,
        minio_key,
        expires_seconds=expires_seconds,
    )
    if not url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not generate download URL",
        )
    return url
