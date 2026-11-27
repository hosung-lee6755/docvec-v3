"""PDF 표 읽기 순서와 번호 재부여(2026-11-27, 법령심사 보고서 2쪽과 9쪽, 11쪽)."""
from app.pipeline.adapters.base import RawPage, RawParsedDocument, RawTableCandidate, RawTextBlock
from app.pipeline.adapters.table_order import renumber_tables, sorted_by_reading_order


def _table(page: int, top: float, name: str, detected_as: str = "ruled") -> tuple[RawTableCandidate, RawTextBlock]:
    bbox = (20.0, top, 700.0, top + 50.0)
    candidate = RawTableCandidate(page_number=page, rows=[[name]], bbox=bbox, detected_as=detected_as)
    block = RawTextBlock(text=f"[표 99]\n| {name} |", page_number=page, bbox=bbox, block_type="table")
    return candidate, block


def _page(number: int, tables: list[tuple[RawTableCandidate, RawTextBlock]]) -> RawPage:
    body = RawTextBlock(text=f"{number}쪽 본문", page_number=number, block_type="paragraph")
    return RawPage(
        page_number=number, width=780, height=540,
        text_blocks=[body, *(block for _, block in tables)],
        table_candidates=[candidate for candidate, _ in tables],
        image_regions=[],
    )


def test_tables_on_one_page_are_ordered_top_to_bottom():
    # 선 표 찾기가 면적 큰 아래 표를 먼저 돌려줬다
    lower, upper = _table(2, 250, "개정이력")[0], _table(2, 110, "결재")[0]

    assert [t.rows[0][0] for t in sorted_by_reading_order([lower, upper])] == ["결재", "개정이력"]


def test_ocr_layout_tables_use_bottom_origin_coordinates():
    # scan_layout 표는 Docling 좌표(아래쪽 원점)라 위 가장자리 값이 클수록 위에 있다
    top_table, _ = _table(9, 400, "위", "ocr_layout")
    bottom_table, _ = _table(9, 100, "아래", "ocr_layout")

    assert [t.rows[0][0] for t in sorted_by_reading_order([bottom_table, top_table])] == ["위", "아래"]


def test_renumber_follows_pages_and_positions_and_keeps_blocks_paired_with_tables():
    page2 = _page(2, [_table(2, 250, "개정이력"), _table(2, 110, "결재")])
    page9 = _page(9, [_table(9, 300, "OCR 표", "ocr_layout")])
    page11 = _page(11, [_table(11, 100, "11쪽 표")])
    parsed = RawParsedDocument(format_id="pdf", page_count=11, pages=[page11, page2, page9], metadata={}, warnings=[])

    changed = renumber_tables(parsed)

    ordered = sorted(parsed.pages, key=lambda p: p.page_number)
    tables = [(page.page_number, t.rows[0][0]) for page in ordered for t in page.table_candidates]
    markers = [b.text.split("\n") for page in ordered for b in page.text_blocks if b.block_type == "table"]
    assert tables == [(2, "결재"), (2, "개정이력"), (9, "OCR 표"), (11, "11쪽 표")]
    assert markers == [["[표 1]", "| 결재 |"], ["[표 2]", "| 개정이력 |"], ["[표 3]", "| OCR 표 |"], ["[표 4]", "| 11쪽 표 |"]]
    assert page2.text_blocks[0].text == "2쪽 본문"
    assert changed == 4


def test_renumber_leaves_a_page_alone_when_blocks_and_tables_do_not_pair_up():
    candidate, block = _table(1, 100, "표")
    other = RawTextBlock(text="[표 98]\n| 다른 |", page_number=1, block_type="table")
    page = RawPage(page_number=1, width=1, height=1, text_blocks=[block, other], table_candidates=[candidate],
                   image_regions=[])
    parsed = RawParsedDocument(format_id="pdf", page_count=1, pages=[page], metadata={}, warnings=[])

    assert renumber_tables(parsed) == 0
    assert page.text_blocks[0].text.startswith("[표 99]")
