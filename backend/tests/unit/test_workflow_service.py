"""Unit coverage for workflow_service.validate_graph — graph well-formedness
checks (unknown block type, missing incoming/outgoing edges, cycles)."""
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.services.workflow_service import validate_graph


def _block(block_id, block_type, label=None):
    b = MagicMock()
    b.id = block_id
    b.block_type = block_type
    b.label = label
    return b


def _edge(from_id, to_id):
    e = MagicMock()
    e.from_block_id = from_id
    e.to_block_id = to_id
    return e


def _mock_db(blocks, edges):
    db = AsyncMock()
    blocks_result = MagicMock()
    blocks_result.all.return_value = blocks
    edges_result = MagicMock()
    edges_result.all.return_value = edges
    db.scalars = AsyncMock(side_effect=[blocks_result, edges_result])
    return db


@pytest.mark.asyncio
async def test_empty_graph_is_invalid():
    db = _mock_db([], [])
    errors = await validate_graph(db, str(uuid4()))
    assert errors == ["워크플로우에 블록이 하나도 없습니다"]


@pytest.mark.asyncio
async def test_linear_input_to_output_is_valid():
    input_id, output_id = uuid4(), uuid4()
    blocks = [_block(input_id, "input"), _block(output_id, "output")]
    edges = [_edge(input_id, output_id)]
    db = _mock_db(blocks, edges)
    errors = await validate_graph(db, str(uuid4()))
    assert errors == []


@pytest.mark.asyncio
async def test_unknown_block_type_is_rejected():
    block_id = uuid4()
    blocks = [_block(block_id, "not_a_real_block")]
    db = _mock_db(blocks, [])
    errors = await validate_graph(db, str(uuid4()))
    assert any("유형이 올바르지 않습니다" in e for e in errors)


@pytest.mark.asyncio
async def test_non_input_block_without_incoming_edge_is_rejected():
    orphan_id = uuid4()
    blocks = [_block(orphan_id, "preprocess", label="전처리")]
    db = _mock_db(blocks, [])
    errors = await validate_graph(db, str(uuid4()))
    assert any("입력이 없습니다" in e for e in errors)


@pytest.mark.asyncio
async def test_non_output_block_without_outgoing_edge_is_rejected():
    dangling_id = uuid4()
    blocks = [_block(dangling_id, "input", label="입력")]
    db = _mock_db(blocks, [])
    errors = await validate_graph(db, str(uuid4()))
    assert any("출력이 없습니다" in e for e in errors)


@pytest.mark.asyncio
async def test_cycle_is_rejected():
    a, b, c = uuid4(), uuid4(), uuid4()
    blocks = [_block(a, "input"), _block(b, "preprocess"), _block(c, "output")]
    # a -> b -> c -> b is a cycle back into b
    edges = [_edge(a, b), _edge(b, c), _edge(c, b)]
    db = _mock_db(blocks, edges)
    errors = await validate_graph(db, str(uuid4()))
    assert any("순환 참조" in e for e in errors)


@pytest.mark.asyncio
async def test_branch_and_merge_is_valid():
    input_id, branch_id, merge_id, output_id = uuid4(), uuid4(), uuid4(), uuid4()
    blocks = [
        _block(input_id, "input"),
        _block(branch_id, "branch"),
        _block(merge_id, "merge"),
        _block(output_id, "output"),
    ]
    edges = [
        _edge(input_id, branch_id),
        _edge(branch_id, merge_id),
        _edge(merge_id, output_id),
    ]
    db = _mock_db(blocks, edges)
    errors = await validate_graph(db, str(uuid4()))
    assert errors == []
