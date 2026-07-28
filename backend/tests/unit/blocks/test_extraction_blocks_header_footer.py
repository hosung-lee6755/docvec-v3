from app.pipeline.adapters.base import RawPage, RawParsedDocument
from app.pipeline.blocks.extraction_blocks import (
    _detect_header_footer_footnote_lines,
    _strip_excluded_lines,
    _strip_nul_bytes,
)


def _line(page_number, text, bbox):
    return {"page_number": page_number, "text": text, "bbox": bbox, "font_size": 11.0}


def _make_parsed(num_pages, header=None, footer=None, footnote=None):
    page_height = 842
    line_layout = []
    pages = []
    for i in range(1, num_pages + 1):
        if header:
            line_layout.append(_line(i, header, (50, 20, 200, 35)))
        line_layout.append(_line(i, f"Body paragraph for page {i}.", (50, 400, 300, 415)))
        if footer:
            line_layout.append(_line(i, footer, (50, 800, 200, 815)))
        if footnote and i == 1:
            line_layout.append(_line(i, footnote, (50, 790, 300, 805)))
        pages.append(RawPage(
            page_number=i, width=595, height=page_height,
            text_blocks=[], table_candidates=[], image_regions=[],
        ))
    return RawParsedDocument(
        format_id="pdf", page_count=num_pages, pages=pages,
        metadata={"line_layout": line_layout}, warnings=[],
    )


def test_repeated_margin_text_is_detected_and_tagged():
    parsed = _make_parsed(3, header="회사명 기밀문서", footer="© 2026 Example Corp")

    excluded = _detect_header_footer_footnote_lines(parsed)

    assert excluded == {"회사명 기밀문서", "© 2026 Example Corp"}
    roles = {line["text"]: line["role"] for line in parsed.metadata["line_layout"]}
    assert roles["회사명 기밀문서"] == "header"
    assert roles["© 2026 Example Corp"] == "footer"


def test_body_text_is_never_flagged_as_header_or_footer():
    parsed = _make_parsed(3, header="Repeated Header", footer="Repeated Footer")

    _detect_header_footer_footnote_lines(parsed)

    body_roles = {
        line["role"] for line in parsed.metadata["line_layout"]
        if line["text"].startswith("Body paragraph")
    }
    assert body_roles == {None}


def test_single_page_document_never_flags_header_footer():
    parsed = _make_parsed(1, header="Looks like a header", footer="Looks like a footer")

    excluded = _detect_header_footer_footnote_lines(parsed)

    assert excluded == set()


def test_page_varying_line_is_not_falsely_matched_as_repeated():
    # A page-number-style footer ("Page 1 of 3", "Page 2 of 3", ...) differs
    # per page, so exact-text repetition matching correctly does NOT catch
    # it — a known, documented limitation, not a false positive to guard.
    line_layout = []
    pages = []
    for i in range(1, 4):
        line_layout.append(_line(i, f"Page {i} of 3", (50, 800, 200, 815)))
        pages.append(RawPage(page_number=i, width=595, height=842, text_blocks=[], table_candidates=[], image_regions=[]))
    parsed = RawParsedDocument(format_id="pdf", page_count=3, pages=pages, metadata={"line_layout": line_layout}, warnings=[])

    excluded = _detect_header_footer_footnote_lines(parsed)

    assert excluded == set()


def test_footnote_marker_is_tagged_but_not_excluded():
    parsed = _make_parsed(3, footnote="1) 각주 설명 텍스트입니다.")

    excluded = _detect_header_footer_footnote_lines(parsed)

    footnote_line = next(
        line for line in parsed.metadata["line_layout"] if line["text"].startswith("1)")
    )
    assert footnote_line["role"] == "footnote"
    assert footnote_line["text"] not in excluded


def test_missing_line_layout_is_a_safe_noop():
    pages = [RawPage(page_number=1, width=595, height=842, text_blocks=[], table_candidates=[], image_regions=[])]
    parsed = RawParsedDocument(format_id="hwp", page_count=1, pages=pages, metadata={}, warnings=[])

    assert _detect_header_footer_footnote_lines(parsed) == set()


def test_strip_excluded_lines_removes_only_matching_lines():
    text = "회사명 기밀문서\nBody paragraph one.\n© 2026 Example Corp"

    result = _strip_excluded_lines(text, {"회사명 기밀문서", "© 2026 Example Corp"})

    assert result == "Body paragraph one."


def test_strip_excluded_lines_is_identity_when_nothing_excluded():
    text = "Line one.\nLine two."

    assert _strip_excluded_lines(text, set()) == text


def test_strip_nul_bytes_removes_nul_from_plain_string():
    assert _strip_nul_bytes("hello\x00world") == "helloworld"


def test_strip_nul_bytes_is_identity_when_no_nul_present():
    text = "정상적인 텍스트입니다."
    assert _strip_nul_bytes(text) is text


def test_strip_nul_bytes_recurses_into_nested_lists_and_dicts():
    value = {
        "text": "표 셀\x00값",
        "rows": [["a\x00b", "clean"], ["c", "d\x00"]],
    }

    result = _strip_nul_bytes(value)

    assert result == {"text": "표 셀값", "rows": [["ab", "clean"], ["c", "d"]]}


def test_strip_nul_bytes_passes_through_non_string_scalars():
    assert _strip_nul_bytes(42) == 42
    assert _strip_nul_bytes(None) is None
