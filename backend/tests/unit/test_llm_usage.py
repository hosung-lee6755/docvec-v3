"""Unit coverage for app.services.llm.estimate_cost_usd -- the pricing math
behind the BYOK usage/cost dashboard."""

import pytest

from app.services.llm import estimate_cost_usd


def test_estimate_cost_usd_computes_blended_input_output_rate():
    # gpt-4o-mini: $0.15/1M input, $0.60/1M output
    cost = estimate_cost_usd("gpt-4o-mini", input_tokens=1_000_000, output_tokens=1_000_000)
    assert cost == pytest.approx(0.75)


def test_estimate_cost_usd_zero_for_unknown_model():
    # Local models aren't in the pricing table -- must never be billed.
    assert estimate_cost_usd("qwen2.5-3b", input_tokens=5000, output_tokens=5000) == 0.0


def test_estimate_cost_usd_scales_with_token_count():
    small = estimate_cost_usd("claude-3-5-sonnet", input_tokens=1000, output_tokens=1000)
    large = estimate_cost_usd("claude-3-5-sonnet", input_tokens=10000, output_tokens=10000)
    assert large == pytest.approx(small * 10)
