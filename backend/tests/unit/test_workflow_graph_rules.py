"""validate_graph(PREPROCESS 규칙/상류 요구/순환/표시 이름)와 reprocess_service의
시작 블록 해석·하류 폐포·영향도 계산 오류 경로 보강 테스트."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.services import workflow_service as ws
from app.services.reprocess_service import (
    ReprocessError,
    compute_reprocess_impact,
    downstream_closure,
    resolve_start_block,
)

# ------------------------------------------------------------ helpers


def _block(block_type, label=None, config=None):
    return SimpleNamespace(id=uuid4(), block_type=block_type, label=label, config=config or {},
                           version_id="v1")


def _edge(src, dst):
    return SimpleNamespace(from_block_id=src.id, to_block_id=dst.id)


def _chain(*blocks):
    return [_edge(a, b) for a, b in zip(blocks, blocks[1:])]


def _db(blocks, edges, *, kind="PREPROCESS"):
    db = AsyncMock()
    blocks_result, edges_result = MagicMock(), MagicMock()
    blocks_result.all.return_value = blocks
    edges_result.all.return_value = edges
    db.scalars = AsyncMock(side_effect=[blocks_result, edges_result])
    version = SimpleNamespace(workflow_id="w1")
    workflow = SimpleNamespace(kind=kind)
    db.get = AsyncMock(side_effect=[version, workflow])
    return db


def _messages(errors):
    return [e["message"] for e in errors]


# ----------------------------------------------------------- display names


def test_display_names_prefer_label_then_numbered_type_name():
    labelled = _block("text_extract", label="내 추출")
    first, second = _block("text_clean"), _block("text_clean")
    solo = _block("chunk_split")

    names = ws._display_names([labelled, first, second, solo])

    assert names[str(labelled.id)] == "내 추출"
    assert names[str(first.id)] == f"{ws.BLOCK_TYPE_LABELS.get('text_clean', 'text_clean')} 1"
    assert names[str(second.id)].endswith(" 2")
    assert names[str(solo.id)] == ws.BLOCK_TYPE_LABELS.get("chunk_split", "chunk_split")


def test_display_names_fall_back_to_raw_type_for_unknown_block():
    block = _block("mystery")

    assert ws._display_names([block])[str(block.id)] == "mystery"


# ----------------------------------------------------------- graph walkers


def test_upstream_block_types_collects_transitive_sources_and_survives_cycles():
    a, b, c = _block("format_detect"), _block("text_extract"), _block("text_clean")
    by_id = {str(x.id): x for x in (a, b, c)}
    incoming = {str(a.id): [_edge(c, a)], str(b.id): [_edge(a, b)], str(c.id): [_edge(b, c)]}

    assert ws._upstream_block_types(str(c.id), by_id, incoming) == {
        "format_detect", "text_extract", "text_clean",
    }


def test_find_cycle_detects_loop_and_accepts_dag():
    a, b, c = _block("x"), _block("y"), _block("z")
    by_id = {str(x.id): x for x in (a, b, c)}

    def outgoing(edges):
        out: dict[str, list] = {}
        for e in edges:
            out.setdefault(str(e.from_block_id), []).append(e)
        return out

    assert ws._find_cycle(by_id, outgoing(_chain(a, b, c))) is None
    assert "순환 참조" in ws._find_cycle(by_id, outgoing(_chain(a, b, c) + [_edge(c, a)]))


# --------------------------------------------------------- validate_graph


@pytest.mark.asyncio
async def test_valid_preprocess_pipeline_has_no_errors():
    blocks = [_block(t) for t in (
        "file_validate", "format_detect", "text_extract", "text_clean", "chunk_split",
        "quality_check", "rag_store",
    )]

    errors = await ws.validate_graph(_db(blocks, _chain(*blocks)), "v1")

    assert errors == []


@pytest.mark.asyncio
async def test_preprocess_requires_exactly_one_entry_file_validate_and_one_rag_store():
    a, b = _block("format_detect"), _block("text_extract")
    errors = await ws.validate_graph(_db([a, b], _chain(a, b)), "v1")

    messages = _messages(errors)
    assert any("'파일 검증' 정확히 1개" in m for m in messages)
    assert any("'RAG 저장' 블록이 정확히 1개" in m for m in messages)


@pytest.mark.asyncio
async def test_block_missing_required_upstream_type_is_reported_with_block_id():
    fv, extract = _block("file_validate"), _block("text_extract")
    rag = _block("rag_store")
    errors = await ws.validate_graph(_db([fv, extract, rag], _chain(fv, extract, rag)), "v1")

    flagged = [e for e in errors if "상류에" in e["message"]]
    assert {e["block_id"] for e in flagged} == {str(extract.id), str(rag.id)}
    assert any("format_detect" in e["message"] for e in flagged)
    assert any("chunk_split" in e["message"] and "quality_check" in e["message"] for e in flagged)


@pytest.mark.asyncio
async def test_disconnected_blocks_report_missing_input_and_output_by_name():
    fv, orphan = _block("file_validate"), _block("text_clean", label="고아 블록")
    errors = await ws.validate_graph(_db([fv, orphan], []), "v1")

    messages = _messages(errors)
    assert "'고아 블록' 블록에 연결된 입력이 없습니다" in messages
    assert "'고아 블록' 블록에 연결된 출력이 없습니다" in messages
    assert not any("입력이 없습니다" in m and "파일 검증" in m for m in messages)  # entry is exempt


@pytest.mark.asyncio
async def test_analysis_workflow_uses_output_as_terminal_and_skips_preprocess_rules():
    inp, summarize, out = _block("input"), _block("summarize"), _block("output")

    errors = await ws.validate_graph(
        _db([inp, summarize, out], _chain(inp, summarize, out), kind="ANALYSIS"), "v1"
    )

    assert errors == []


@pytest.mark.asyncio
async def test_cycle_is_reported_as_graph_wide_error():
    a, b = _block("summarize"), _block("classify")
    errors = await ws.validate_graph(
        _db([a, b], [_edge(a, b), _edge(b, a)], kind="ANALYSIS"), "v1"
    )

    cycle = [e for e in errors if "순환 참조" in e["message"]]
    assert cycle and cycle[0]["block_id"] is None


# ------------------------------------------------------ reprocess_service


@pytest.mark.asyncio
async def test_resolve_start_block_by_instance_id():
    block = SimpleNamespace(version_id="v1")
    db = AsyncMock()
    db.get = AsyncMock(return_value=block)

    assert await resolve_start_block(db, "v1", None, "b1") is block


@pytest.mark.asyncio
@pytest.mark.parametrize("found", [None, SimpleNamespace(version_id="other-version")])
async def test_resolve_start_block_rejects_missing_or_foreign_block(found):
    db = AsyncMock()
    db.get = AsyncMock(return_value=found)

    with pytest.raises(ReprocessError, match="지정한 시작 블록"):
        await resolve_start_block(db, "v1", None, "b1")


def _scalars(rows):
    result = MagicMock()
    result.all.return_value = rows
    return AsyncMock(return_value=result)


@pytest.mark.asyncio
async def test_resolve_start_block_by_unique_type():
    block = SimpleNamespace(version_id="v1")
    db = AsyncMock()
    db.scalars = _scalars([block])

    assert await resolve_start_block(db, "v1", "summarize", None) is block


@pytest.mark.asyncio
@pytest.mark.parametrize("rows,fragment", [
    ([], "타입의 블록이 이 워크플로우에 없습니다"),
    ([object(), object()], "여러 개 있어 특정할 수 없습니다"),
])
async def test_resolve_start_block_by_type_requires_exactly_one_match(rows, fragment):
    db = AsyncMock()
    db.scalars = _scalars(rows)

    with pytest.raises(ReprocessError, match=fragment):
        await resolve_start_block(db, "v1", "summarize", None)


def test_downstream_closure_follows_branches_once_including_start():
    a, b, c, d, e = (_block(t) for t in "abcde")
    edges = [_edge(a, b), _edge(b, c), _edge(b, d), _edge(c, d), _edge(e, a)]

    closure = downstream_closure([a, b, c, d, e], edges, str(b.id))

    assert closure == {str(b.id), str(c.id), str(d.id)}  # upstream a/e excluded


@pytest.mark.asyncio
async def test_impact_rejects_document_never_processed_by_workflow():
    doc = SimpleNamespace(active_run_id=None)

    with pytest.raises(ReprocessError, match="워크플로우로 처리된 적이 없어"):
        await compute_reprocess_impact(AsyncMock(), doc, _block("summarize"))


@pytest.mark.asyncio
async def test_impact_rejects_when_original_run_record_is_gone():
    db = AsyncMock()
    db.get = AsyncMock(return_value=None)

    with pytest.raises(ReprocessError, match="원본 실행 기록"):
        await compute_reprocess_impact(db, SimpleNamespace(active_run_id="r"), _block("x"))


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["RUNNING", "QUEUED", "WAITING_REVIEW"])
async def test_impact_blocks_reprocess_while_original_run_is_live(status):
    db = AsyncMock()
    db.get = AsyncMock(return_value=SimpleNamespace(status=status))

    with pytest.raises(ReprocessError, match="아직 완료되지 않았습니다"):
        await compute_reprocess_impact(db, SimpleNamespace(active_run_id="r"), _block("x"))


@pytest.mark.asyncio
async def test_impact_rejects_start_when_an_upstream_block_never_completed():
    up, start = _block("text_extract"), _block("summarize")
    parent = SimpleNamespace(id="r0", version_id="v1", status="COMPLETED")
    db = AsyncMock()
    db.get = AsyncMock(return_value=parent)
    db.scalars = AsyncMock(side_effect=[
        MagicMock(all=lambda: [up, start]),
        MagicMock(all=lambda: _chain(up, start)),
        MagicMock(all=lambda: [SimpleNamespace(block_instance_id=up.id, status="FAILED")]),
    ])

    with pytest.raises(ReprocessError, match=r"상류 블록\('text_extract'\)이 완료되지 않아"):
        await compute_reprocess_impact(db, SimpleNamespace(active_run_id="r0", id="d"), start)


@pytest.mark.asyncio
async def test_impact_summarises_affected_blocks_counts_and_full_reprocess_flag():
    entry, mid = _block("file_validate"), _block("summarize")
    parent = SimpleNamespace(id="r0", version_id="v1", status="FAILED")
    db = AsyncMock()
    db.get = AsyncMock(return_value=parent)
    db.scalars = AsyncMock(side_effect=[
        MagicMock(all=lambda: [entry, mid]),
        MagicMock(all=lambda: _chain(entry, mid)),
        MagicMock(all=lambda: []),
    ])
    db.scalar = AsyncMock(side_effect=[7, None])

    result = await compute_reprocess_impact(
        db, SimpleNamespace(active_run_id="r0", id="d"), entry, reason="사전 변경"
    )

    assert result.impact == {
        "reason": "사전 변경", "changeType": "MANUAL",
        "affectedBlocks": ["file_validate", "summarize"],
        "affectedNodeCount": 7, "affectedChunkCount": 0,
        "fullReprocessingRequired": True,  # starting at the entry block == everything reruns
    }
    assert result.upstream_blocks == []
