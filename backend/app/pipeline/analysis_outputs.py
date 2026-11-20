"""분석 워크플로우가 문서에 남기는 항목과, 남기지 않는 항목 비우기(2026-11-20 사용자 지시).

분석 결과는 출력 블록(output, 문서에 저장)이 문서에 쓴다(output_blocks.OutputBlock).
- 요약: 요약 블록(summarize)이 있을 때 남는다.
- 추천 태그: 키워드(extract_keywords)나 개체(extract_entities) 블록이 있거나,
  분류를 태그로도 쓰는 분류 블록이 있을 때 남는다.
- 분류: 분류 블록(classify)이 있을 때 남는다.

사용자 워크플로우를 그대로 따른다. 워크플로우에 없는 단계를 시스템이 몰래 채우지 않고,
예전 실행이 남긴 값도 남기지 않는다. 남겨 두면 지금 워크플로우가 만든 결과처럼 보이기 때문이다.
블록을 잇는 선은 보지 않는다. 게시 전 검사가 끊긴 블록을 막기 때문이다.

화면(컬렉션의 분석 워크플로우 지정)도 같은 규칙으로 빠지는 항목을 알린다
(frontend/src/lib/analysisOutputs.ts).
"""
from collections.abc import Iterable

SUMMARY = "summary"
TAGS = "tags"
CATEGORY = "category"

# 요약, 태그, 분류를 만들지 않았다는 표시.
# 화면은 이 값을 보고 "이 워크플로우에는 요약 단계가 없다"고 알린다
SKIPPED = "SKIPPED"

_TAG_BLOCKS = frozenset({"extract_keywords", "extract_entities"})


def analysis_outputs(blocks: Iterable[tuple[str, dict | None]]) -> set[str]:
    """(블록 종류, 설정) 목록으로 이 워크플로우가 문서에 남기는 항목을 고른다."""
    listed = [(block_type, config or {}) for block_type, config in blocks]
    savers = [config for block_type, config in listed if block_type == "output"
              and config.get("save_to_document", True) is not False]
    if not savers:
        return set()
    types = {block_type for block_type, _ in listed}
    produced: set[str] = set()
    if "summarize" in types:
        produced.add(SUMMARY)
    if "classify" in types:
        produced.add(CATEGORY)
    category_as_tag = "classify" in types and any(
        config.get("category_as_tag", True) for config in savers
    )
    if types & _TAG_BLOCKS or category_as_tag:
        produced.add(TAGS)
    return produced


def clear_unproduced_fields(document, produced: set[str]) -> list[str]:
    """워크플로우가 만들지 않는 항목을 비우고 비운 항목 이름을 돌려준다. 사용자가 단 태그(tags)와
    사용자가 직접 고친 분류(user_edited_fields)는 건드리지 않는다."""
    cleared: list[str] = []
    if SUMMARY not in produced:
        document.summary = None
        document.summary_status = SKIPPED
        cleared.append(SUMMARY)
    if TAGS not in produced:
        document.suggested_tags = None
        cleared.append(TAGS)
    if CATEGORY not in produced and "category" not in (document.user_edited_fields or []):
        document.category = None
        cleared.append(CATEGORY)
    if TAGS not in produced and CATEGORY not in produced:
        document.metadata_status = SKIPPED
    return cleared
