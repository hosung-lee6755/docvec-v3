"""Unit coverage for the workflows API endpoints — version-immutability
enforcement (409 on mutating/re-publishing a published version) and the
block-types listing, following test_collection_vector_stats.py's style
(AsyncMock db, patch at the endpoint's import site, direct function calls)."""
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints.workflows import (
    GraphUpdate,
    publish_version,
    update_graph,
    list_block_types,
)
from app.pipeline.blocks.registry import BLOCK_REGISTRY


@pytest.mark.asyncio
async def test_list_block_types_returns_registry_keys():
    result = await list_block_types(current_user=MagicMock())
    assert {item["block_type"] for item in result["items"]} == set(BLOCK_REGISTRY.keys())


@pytest.mark.asyncio
async def test_update_graph_rejects_published_version():
    workflow_id, version_id = uuid4(), uuid4()
    workflow = MagicMock(id=workflow_id, project_id=uuid4())
    published_version = MagicMock(workflow_id=workflow_id, published_at="2026-07-13T00:00:00")

    db = AsyncMock()
    db.get = AsyncMock(side_effect=[workflow, published_version])

    with patch(
        "app.api.v1.endpoints.workflows.access.check_project_access",
        new=AsyncMock(return_value=workflow),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await update_graph(
                workflow_id, version_id, GraphUpdate(blocks=[], edges=[]),
                db=db, current_user=MagicMock(),
            )

    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_publish_version_rejects_already_published():
    workflow_id, version_id = uuid4(), uuid4()
    workflow = MagicMock(id=workflow_id, project_id=uuid4())
    published_version = MagicMock(workflow_id=workflow_id, published_at="2026-07-13T00:00:00")

    db = AsyncMock()
    db.get = AsyncMock(side_effect=[workflow, published_version])

    with patch(
        "app.api.v1.endpoints.workflows.access.check_project_access",
        new=AsyncMock(return_value=workflow),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await publish_version(workflow_id, version_id, db=db, current_user=MagicMock())

    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_publish_version_rejects_when_graph_invalid():
    workflow_id, version_id = uuid4(), uuid4()
    workflow = MagicMock(id=workflow_id, project_id=uuid4())
    draft_version = MagicMock(workflow_id=workflow_id, published_at=None)

    db = AsyncMock()
    db.get = AsyncMock(side_effect=[workflow, draft_version])

    with (
        patch(
            "app.api.v1.endpoints.workflows.access.check_project_access",
            new=AsyncMock(return_value=workflow),
        ),
        patch(
            "app.api.v1.endpoints.workflows.versions.validate_graph",
            new=AsyncMock(return_value=[{"message": "워크플로우에 블록이 하나도 없습니다", "block_id": None}]),
        ),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await publish_version(workflow_id, version_id, db=db, current_user=MagicMock())

    assert exc_info.value.status_code == 409
