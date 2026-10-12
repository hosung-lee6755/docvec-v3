"""좌표 없는 워크플로우 블록 배치 마이그레이션의 순수 함수 검증(DB 불필요)."""
import importlib.util
from pathlib import Path

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic" / "versions" / "3c5e7a9b1d2f_layout_blocks_without_position.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("layout_migration", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


layout = _load()


def test_chain_without_positions_is_laid_out_in_edge_order_without_overlap():
    blocks = [("c", {}), ("a", {}), ("b", {})]
    edges = [("a", "b"), ("b", "c")]

    result = layout._layout_positions(blocks, edges)

    # 위→아래로 쌓는다: 카드의 연결 핸들이 위(입력)·아래(출력)에 있다.
    assert [result[i]["y"] for i in ("a", "b", "c")] == [0, layout.LAYOUT_Y_GAP, 2 * layout.LAYOUT_Y_GAP]
    assert {p["x"] for p in result.values()} == {0}


def test_blocks_continue_in_the_next_column_after_the_row_limit():
    ids = [f"b{i:02d}" for i in range(layout.LAYOUT_ROWS + 1)]
    blocks = [(i, {}) for i in ids]
    edges = list(zip(ids, ids[1:]))

    result = layout._layout_positions(blocks, edges)

    assert result[ids[layout.LAYOUT_ROWS - 1]] == {"x": 0, "y": (layout.LAYOUT_ROWS - 1) * layout.LAYOUT_Y_GAP}
    assert result[ids[layout.LAYOUT_ROWS]] == {"x": layout.LAYOUT_X_GAP, "y": 0}


def test_gaps_are_larger_than_the_block_card_so_blocks_do_not_overlap():
    assert layout.LAYOUT_X_GAP > 287
    assert layout.LAYOUT_Y_GAP > 68


def test_blocks_that_already_have_positions_are_left_alone():
    blocks = [("a", {"x": 0, "y": 0}), ("b", {"x": 240, "y": 0})]

    assert layout._layout_positions(blocks, [("a", "b")]) == {}


def test_only_missing_blocks_are_placed_below_existing_ones_when_mixed():
    blocks = [("a", {"x": 0, "y": 40}), ("b", {})]

    result = layout._layout_positions(blocks, [("a", "b")])

    assert set(result) == {"b"}
    assert result["b"]["y"] == 40 + layout.LAYOUT_Y_GAP


def test_cycle_does_not_hang_and_every_block_gets_a_distinct_slot():
    blocks = [("a", {}), ("b", {})]

    result = layout._layout_positions(blocks, [("a", "b"), ("b", "a")])

    assert len({(p["x"], p["y"]) for p in result.values()}) == 2


def test_has_position_requires_numeric_x_and_y():
    assert layout._has_position({"x": 1, "y": 2})
    assert not layout._has_position({})
    assert not layout._has_position({"x": 1})
    assert not layout._has_position(None)
