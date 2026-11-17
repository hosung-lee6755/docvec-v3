"""인용 위치 표시(전체 점검 1-7): 표시할 쪽과 영역을 정하고 그 쪽을 그린다."""
from types import SimpleNamespace

import fitz
import pytest

from app.services import citation_highlight as ch


def _chunk(**kwargs):
    base = {"element_id": None, "page_start": None, "original_text": None, "chunk_text": ""}
    return SimpleNamespace(**{**base, **kwargs})


def _pdf(lines_by_page):
    doc = fitz.open()
    for lines in lines_by_page:
        page = doc.new_page(width=400, height=300)
        for i, line in enumerate(lines):
            page.insert_text((40, 60 + i * 30), line, fontsize=12)
    data = doc.tobytes()
    doc.close()
    return data


def _yellow_pixels(png: bytes) -> int:
    pix = fitz.Pixmap(png)
    samples, n = pix.samples, pix.n
    return sum(
        1 for i in range(0, len(samples), n * 7)
        if samples[i] > 200 and samples[i + 1] > 180 and samples[i + 2] < 215 and samples[i] - samples[i + 2] > 30
    )


def test_snippets_skip_table_rows_and_short_lines_and_are_capped():
    text = "[표 1]\n| a | b |\n짧다\n접수 기간은 6월 8일부터 16일까지이다. 이후에는 받지 않는다.\n" + "\n".join(
        f"열두 줄을 넘기는 본문 {i}번" for i in range(20)
    )

    snippets = ch.snippets_from(text)

    assert snippets[0] == "접수 기간은 6월 8일부터 16일까지이다. 이후에는 받지 않는다."[:30]
    assert len(snippets) == 12 and all(not s.startswith("|") for s in snippets)


def test_target_uses_element_boxes_of_the_chunk_page_only():
    elements = [
        {"id": "e1", "page": 2, "bbox": [10, 200, 100, 180]},
        {"id": "e2", "page": 3, "bbox": [10, 100, 100, 80]},
        {"id": "other", "page": 2, "bbox": [0, 0, 1, 1]},
        {"id": "e3", "page": 2},  # 좌표가 없는 요소
        "broken",
    ]

    target = ch.build_target(_chunk(element_id="e1", page_start=2, chunk_text="본문 한 줄입니다"), ["e2", "e3"], elements)

    assert target.page_number == 2 and target.boxes == ((10.0, 200.0, 100.0, 180.0),)
    assert target.snippets == ("본문 한 줄입니다",)


def test_target_falls_back_to_first_element_page_then_page_one():
    elements = [{"id": "e1", "page": 4, "bbox": [1, 2, 3, 4]}]

    assert ch.build_target(_chunk(), ["e1"], elements).page_number == 4
    assert ch.build_target(_chunk(original_text="원문 줄을 우선한다", chunk_text="x"), [], None) == ch.HighlightTarget(
        page_number=1, boxes=(), snippets=("원문 줄을 우선한다",),
    )


def test_render_draws_docling_boxes_given_in_bottom_left_coordinates():
    pdf = _pdf([["first page"], ["second page"]])
    plain, _, none = ch.render_highlight(pdf, ch.HighlightTarget(2, (), ()))

    png, page, count = ch.render_highlight(pdf, ch.HighlightTarget(2, ((40.0, 260.0, 200.0, 220.0),), ("ignored",)))

    assert (page, count, none) == (2, 1, 0) and png.startswith(b"\x89PNG")
    assert _yellow_pixels(png) > _yellow_pixels(plain) + 50


def test_render_searches_the_text_layer_when_there_are_no_boxes():
    pdf = _pdf([["Reception period: June 8", "Contact the help desk"]])

    _, page, found = ch.render_highlight(pdf, ch.HighlightTarget(1, (), ("Reception period", "not on this page")))
    _, _, missing = ch.render_highlight(pdf, ch.HighlightTarget(1, (), ("nothing matches",)))

    assert (page, found, missing) == (1, 1, 0)


def test_render_clamps_the_page_and_rejects_empty_pdfs():
    pdf = _pdf([["only page"]])

    assert ch.render_highlight(pdf, ch.HighlightTarget(9, (), ()))[1] == 1
    assert ch.render_highlight(pdf, ch.HighlightTarget(0, (), ()))[1] == 1
    with pytest.raises(Exception):
        ch.render_highlight(b"not a pdf", ch.HighlightTarget(1, (), ()))


def test_render_moves_to_the_page_where_the_text_is_when_the_page_number_is_off():
    pdf = _pdf([["cover"], ["unrelated"], ["Bearing replacement plan", "Bearing replacement budget"]])

    _, page, count = ch.render_highlight(pdf, ch.HighlightTarget(1, (), ("Bearing replacement",)))

    assert (page, count) == (3, 2)
