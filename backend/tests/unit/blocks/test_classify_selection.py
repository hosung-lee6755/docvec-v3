"""분류 블록: 모델 응답에서 카테고리를 고르는 규칙.

모델은 카테고리 이름만 답하라는 지시를 어기고 후보를 나열하거나 문장으로 답하기도 한다.
후보 목록의 앞쪽 항목을 먼저 찾으면 그런 응답이 항상 첫 후보("공고문")로 분류돼, 실제 문서
15건 중 7건이 사례집·가이드라인·연구보고서인데도 공고문이 됐다. 응답에서 먼저 언급된
후보를 고르고, 응답이 후보 하나와 정확히 같으면 그것을 우선한다.
"""
import pytest

from app.pipeline.blocks import content_blocks as cb
from app.pipeline.blocks.base import BlockContext

CATEGORIES = ["공고문", "제안서", "진단보고서", "가이드라인", "사례집", "보고서", "기타"]


def _classify(monkeypatch, answer: str, categories=None) -> str:
    monkeypatch.setattr(cb, "_generate", lambda system_prompt, user_content: answer)
    ctx = BlockContext(
        run_id="r", block_instance_id="b",
        upstream_outputs={"up": {"text": "본문"}},
        config={"categories": categories or CATEGORIES},
    )
    return cb.ClassifyBlock().run(ctx).output["category"]


@pytest.mark.parametrize("category", CATEGORIES)
def test_exact_answer_is_chosen(monkeypatch, category):
    assert _classify(monkeypatch, category) == category


def test_exact_answer_ignores_surrounding_punctuation(monkeypatch):
    assert _classify(monkeypatch, " '사례집'. ") == "사례집"


def test_first_mentioned_category_wins_over_list_order(monkeypatch):
    # "공고문"이 목록 앞쪽이지만 응답에서는 "사례집"이 먼저 나온다.
    assert _classify(monkeypatch, "사례집에 가깝습니다. 공고문은 아닙니다.") == "사례집"


def test_longer_category_wins_when_a_shorter_one_is_its_substring(monkeypatch):
    # "진단보고서" 안에 "보고서"가 들어 있어도 같은 위치에서는 더 긴 후보를 고른다.
    assert _classify(monkeypatch, "진단보고서입니다") == "진단보고서"


def test_blank_configured_categories_are_ignored(monkeypatch):
    # UI 설정에 빈 항목이 섞여도 `"" in 응답` 이 항상 참이라 모든 문서가 빈 카테고리가 되면 안 된다.
    answer = _classify(monkeypatch, "사례집입니다", categories=["", "  ", "공고문", "사례집", "기타"])

    assert answer == "사례집"


def test_blank_categories_do_not_become_the_fallback(monkeypatch):
    answer = _classify(monkeypatch, "모르겠습니다", categories=["공고문", "기타", ""])

    assert answer == "기타"


def test_falls_back_to_last_category_when_nothing_matches(monkeypatch):
    assert _classify(monkeypatch, "모르겠습니다") == "기타"
