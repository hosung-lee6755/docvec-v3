"""스캔 PDF의 표와 그림 덧붙이기(전체 점검 1-3)."""
from pathlib import Path
from unittest.mock import patch

from app.pipeline.adapters import scan_layout as sl
from app.pipeline.adapters.base import RawPage, RawParsedDocument, RawTextBlock
from app.pipeline.blocks import extraction_blocks as eb


def _parsed(page_count=2, existing_tables=0):
    pages = []
    for number in range(1, page_count + 1):
        blocks = [RawTextBlock(text=f"{number}쪽 본문", page_number=number, block_type="ocr")]
        pages.append(RawPage(
            page_number=number, width=595, height=842, text_blocks=blocks, table_candidates=[], image_regions=[],
        ))
    for i in range(existing_tables):
        pages[0].text_blocks.append(RawTextBlock(text=f"[표 {i + 1}]\n| a |", page_number=1, block_type="table"))
    return RawParsedDocument(format_id="pdf", page_count=page_count, pages=pages, metadata={}, warnings=[])


def _table(page, top=500.0):
    return {"page": page, "bbox": (50.0, top, 300.0, top - 100), "rows": [["구분", "값"], ["가", "1"]]}


def test_merge_appends_tables_after_the_page_text_and_continues_numbering():
    parsed = _parsed(existing_tables=1)

    added = sl.merge_layout(parsed, [_table(2, top=200.0), _table(2, top=700.0), _table(1)], [])

    assert added == {"tables": 3, "figures": 0}
    second = parsed.pages[1]
    # 본문 OCR은 그대로 두고 그 뒤에 붙인다. 같은 쪽에서는 위에 있는 표가 먼저다
    assert [b.text.split("\n")[0] for b in second.text_blocks] == ["2쪽 본문", "[표 3]", "[표 4]"]
    assert [t.bbox[1] for t in second.table_candidates] == [700.0, 200.0]
    assert parsed.pages[0].text_blocks[-1].text.startswith("[표 2]\n")
    candidate = second.table_candidates[0]
    assert (candidate.detected_as, candidate.confidence) == ("ocr_layout", 0.6)
    assert second.text_blocks[1].block_type == "table"


def test_merge_adds_pictures_and_ignores_pages_that_do_not_exist():
    parsed = _parsed()
    pictures = [{"page": 1, "bbox": (1.0, 2.0, 3.0, 4.0), "image_bytes": b"png"}, {"page": 9, "bbox": (0, 0, 1, 1), "image_bytes": b"x"}]

    added = sl.merge_layout(parsed, [_table(9)], pictures)

    assert added == {"tables": 0, "figures": 1}
    assert parsed.pages[0].image_regions[0].image_bytes == b"png"


def test_enrich_reports_what_it_added():
    parsed = _parsed()
    with patch.object(sl, "detect_layout", return_value=([_table(1)], [])):
        added = sl.enrich_scanned_pdf(parsed, Path("scan.pdf"))

    assert added == {"tables": 1, "figures": 0}
    assert "표 1개와 그림 0개" in parsed.warnings[0]


def test_enrich_keeps_the_text_when_detection_fails_or_finds_nothing():
    parsed = _parsed()
    with patch.object(sl, "detect_layout", side_effect=RuntimeError("gpu")):
        assert sl.enrich_scanned_pdf(parsed, Path("scan.pdf")) == {"tables": 0, "figures": 0}
    assert "찾지 못했습니다" in parsed.warnings[0] and len(parsed.pages[0].text_blocks) == 1

    quiet = _parsed()
    with patch.object(sl, "detect_layout", return_value=([], [])):
        sl.enrich_scanned_pdf(quiet, Path("scan.pdf"))
    assert quiet.warnings == []


def test_only_auto_routed_scanned_pdfs_are_enriched():
    note = "텍스트 레이어가 없는 스캔 PDF 라 Docling 대신 전면 OCR 엔진으로 처리했습니다."

    assert eb._is_scanned_pdf_run(Path("a.PDF"), "legacy", note) is True
    assert eb._is_scanned_pdf_run(Path("a.pdf"), "legacy", None) is False     # 사용자가 legacy를 고른 일반 PDF
    assert eb._is_scanned_pdf_run(Path("a.pdf"), "docling", note) is False
    assert eb._is_scanned_pdf_run(Path("a.hwp"), "legacy", note) is False
    assert eb.TextExtractConfig().scan_layout is True


def test_tables_read_from_images_follow_the_same_merge_rule_and_keep_spans():
    # 그림에서 읽은 표도 글자 층 PDF, HWP 표와 같은 합친 칸 규칙을 따르고 합친 칸 목록을 남긴다(2026-11-25).
    # 예전에는 DataFrame 으로 만들어 머리글과 같은 폭으로 합친 칸 "에쓰오씨소프트"가 두 번 나왔다
    from types import SimpleNamespace

    def cell(row, col, text, col_span=1):
        return SimpleNamespace(start_row_offset_idx=row, start_col_offset_idx=col, row_span=1, col_span=col_span,
                               text=text, column_header=row == 0)

    table = SimpleNamespace(data=SimpleNamespace(table_cells=[
        cell(0, 0, "구분"), cell(0, 1, "소속", 2), cell(0, 3, "이름"),
        cell(1, 0, "작성"), cell(1, 1, "에쓰오씨소프트", 2), cell(1, 3, "이호성"),
    ]))

    rows, spans = sl._table_grid(table, document=None)

    assert rows == [["구분", "소속", "", "이름"], ["작성", "에쓰오씨소프트", "", "이호성"]]
    assert {"row": 1, "col": 1, "row_span": 1, "col_span": 2} in spans


def test_merged_spans_reach_the_table_candidate():
    parsed = _parsed()
    spans = [{"row": 0, "col": 0, "row_span": 1, "col_span": 2}]

    sl.merge_layout(parsed, [{**_table(1), "spans": spans}], [])

    assert parsed.pages[0].table_candidates[0].spans == spans


def test_merge_leaves_pages_read_from_the_text_layer_alone():
    """글자 층과 윤곽선 쪽이 섞인 PDF 도 전면 OCR 로 돈다. 글자 층 쪽의 표는 선 표 찾기가 이미 냈으므로 덧붙이지 않는다."""
    parsed = _parsed()
    native = parsed.pages[0]
    native.text_blocks = [RawTextBlock(text="글자 층 본문", page_number=1, block_type="paragraph")]
    pictures = [{"page": 1, "bbox": (1.0, 2.0, 3.0, 4.0), "image_bytes": b"a"}, {"page": 2, "bbox": (1.0, 2.0, 3.0, 4.0), "image_bytes": b"b"}]

    added = sl.merge_layout(parsed, [_table(1), _table(2)], pictures)

    assert added == {"tables": 1, "figures": 1}
    assert native.table_candidates == [] and native.image_regions == []
    assert parsed.pages[1].text_blocks[-1].text.startswith("[표 1]\n")
