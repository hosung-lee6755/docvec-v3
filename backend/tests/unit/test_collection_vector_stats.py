"""Unit coverage for GET /collections/{id}/vector-stats -- the embedding-status
summary combining Postgres document counts with a live Qdrant vector count."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.api.v1.endpoints.collections import get_collection_vector_stats


@pytest.mark.asyncio
async def test_get_collection_vector_stats_combines_pg_and_qdrant_counts():
    collection_id = uuid4()
    collection = MagicMock(embedding_model="bge-m3", reembed_status=None, reembed_progress=None)
    db = AsyncMock()
    db.scalar = AsyncMock(side_effect=[5, 3])  # total_documents, indexed_documents

    with (
        patch(
            "app.api.v1.endpoints.collections.check_collection_access",
            new=AsyncMock(return_value=collection),
        ),
        patch("app.services.qdrant_service.qdrant_service.count_by_collection", return_value=42),
    ):
        result = await get_collection_vector_stats(collection_id, db=db, current_user=MagicMock())

    assert result["embedding_model"] == "bge-m3"
    assert result["dimension"] == 1024
    assert result["total_documents"] == 5
    assert result["indexed_documents"] == 3
    assert result["total_vectors"] == 42
    assert result["reembed_status"] is None
