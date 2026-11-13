"""페이지 맵은 parsed_text와 같은 글자 위치를 써야 한다.

text_extract는 쪽마다 되풀이되는 머리말·꼬리말 줄을 지운 뒤 본문을 만든다. 예전에는 페이지 맵을 지우기 전
블록 길이로 계산해, 지운 글자만큼 쪽 경계가 뒤로 밀렸다. 988쪽 가이드라인에서 청크 719개 중 130개만 쪽이
맞았다(2026-11-13 검토).
"""
from app.pipeline.adapters.base import RawPage, RawTextBlock
from app.pipeline.blocks.extraction_blocks import _assemble_full_text, _page_map_for_assembly
from app.pipeline.tasks.process import _page_number_for_offset


def _page(page_number, *texts):
    return RawPage(
        page_number=page_number, width=595, height=842,
        text_blocks=[RawTextBlock(text=t, page_number=page_number) for t in texts],
        table_candidates=[], image_regions=[],
    )


HEADER = "디지털 정부서비스 UI/UX 가이드라인"


def _pages():
    return [
        _page(1, HEADER, "첫 쪽 본문입니다."),
        _page(2, HEADER, "둘째 쪽 본문입니다.", "- 2 -"),
        _page(3, HEADER, "셋째 쪽 본문입니다."),
    ]


def test_page_boundaries_follow_the_text_after_headers_are_removed():
    pages = _pages()
    excluded = {HEADER, "- 2 -"}

    full_text, _spans = _assemble_full_text(pages, excluded)
    page_map = _page_map_for_assembly(pages, excluded)

    assert page_map[-1][0] == len(full_text)
    for page_no, body in [(1, "첫 쪽"), (2, "둘째 쪽"), (3, "셋째 쪽")]:
        offset = full_text.index(body)
        assert _page_number_for_offset(page_map, offset) == page_no


def test_page_map_matches_old_behaviour_when_nothing_is_removed():
    pages = _pages()

    full_text, _spans = _assemble_full_text(pages, set())
    page_map = _page_map_for_assembly(pages, set())

    assert page_map[-1][0] == len(full_text)
    assert [entry[1] for entry in page_map] == [1, 2, 3]


def test_page_whose_blocks_are_all_removed_does_not_appear():
    pages = [_page(1, "본문 하나."), _page(2, HEADER), _page(3, "본문 셋.")]

    full_text, _spans = _assemble_full_text(pages, {HEADER})
    page_map = _page_map_for_assembly(pages, {HEADER})

    assert [entry[1] for entry in page_map] == [1, 3]
    assert _page_number_for_offset(page_map, full_text.index("본문 셋")) == 3
