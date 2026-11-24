"""H2Orestart가 만든 ODT의 쪽 나눔 보정(preview_odt_fix) 단위 테스트."""

import io
import xml.etree.ElementTree as ET
import zipfile

from app.services.preview_odt_fix import TABLE_TAIL_STYLE, OdtFixReport, fix_hwp_odt

_NS = (
    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" '
    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
    'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
    'xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0" '
    'xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0"'
)


def _layout(name: str, *, margin_bottom: str = "0.5in", footer_height: str = "0in") -> str:
    return (
        f'<style:page-layout style:name="{name}">'
        f'<style:page-layout-properties fo:margin-top="0.7in" fo:margin-bottom="{margin_bottom}"/>'
        '<style:header-style><style:header-footer-properties svg:height="0in" fo:margin-bottom="0in"/></style:header-style>'
        f'<style:footer-style><style:header-footer-properties fo:min-height="{footer_height}" fo:margin-top="0in"/>'
        "</style:footer-style></style:page-layout>"
    )


def _styles(layouts: str, masters: str) -> str:
    return (
        f'<?xml version="1.0" encoding="UTF-8"?><office:document-styles {_NS}>'
        f"<office:automatic-styles>{layouts}</office:automatic-styles>"
        f"<office:master-styles>{masters}</office:master-styles></office:document-styles>"
    )


def _content(body: str, styles: str = "") -> str:
    return (
        f'<?xml version="1.0" encoding="UTF-8"?><office:document-content {_NS}>'
        f"<office:automatic-styles>{styles}</office:automatic-styles>"
        f"<office:body><office:text>{body}</office:text></office:body></office:document-content>"
    )


def _odt(content: str, styles: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as odt:
        odt.writestr(zipfile.ZipInfo("mimetype"), "application/vnd.oasis.opendocument.text")
        odt.writestr("content.xml", content, compress_type=zipfile.ZIP_DEFLATED)
        odt.writestr("styles.xml", styles, compress_type=zipfile.ZIP_DEFLATED)
        odt.writestr("Pictures/a.png", b"\x89PNG", compress_type=zipfile.ZIP_DEFLATED)
    return buffer.getvalue()


def _read(odt: bytes, name: str) -> str:
    with zipfile.ZipFile(io.BytesIO(odt)) as z:
        return z.read(name).decode("utf-8")


def _master(name: str, layout: str, inner: str) -> str:
    return f'<style:master-page style:name="{name}" style:page-layout-name="{layout}">{inner}</style:master-page>'


_EMPTY_HF = (
    '<style:header><text:p text:style-name="Header"/></style:header>'
    '<style:footer><text:p text:style-name="MP1"/><text:p text:style-name="MP2"></text:p></style:footer>'
)
_TABLE = (
    '<table:table table:name="T1"><table:table-row><table:table-cell>'
    "<text:p>칸</text:p></table:table-cell></table:table-row></table:table>"
)


def test_empty_header_and_footer_are_removed_and_their_height_moves_into_the_page_margin():
    # Arrange: 꼬리말 최소 높이 0.5in(한글의 꼬리말 영역)인 빈 꼬리말과 높이 0인 빈 머리말
    styles = _styles(_layout("Mpm2", footer_height="0.5in"), _master("HWP", "Mpm2", _EMPTY_HF))

    # Act
    fixed, report = fix_hwp_odt(_odt(_content("<text:p>본문</text:p>"), styles))

    # Assert: 머리말·꼬리말은 사라지고, 꼬리말 높이만큼 아래 여백이 늘어 본문 높이는 한글과 같다
    out = _read(fixed, "styles.xml")
    assert report.removed_headers_footers == 2
    assert "<style:footer>" not in out and "<style:header>" not in out
    assert 'fo:margin-bottom="1.0000in"' in out
    assert 'fo:margin-top="0.7000in"' in out


def test_footer_with_a_page_number_is_kept():
    footer = (
        '<style:header><text:p text:style-name="Header"/></style:header>'
        '<style:footer><text:p text:style-name="MP1">'
        '<text:page-number text:select-page="current">1</text:page-number></text:p></style:footer>'
    )
    styles = _styles(_layout("Mpm2"), _master("HWP", "Mpm2", footer))

    fixed, report = fix_hwp_odt(_odt(_content("<text:p>본문</text:p>"), styles))

    out = _read(fixed, "styles.xml")
    assert report.removed_headers_footers == 1
    assert "<text:page-number" in out and "<style:header>" not in out


def test_shared_page_layout_is_left_alone_unless_every_master_page_has_the_same_empty_part():
    # Arrange: 두 마스터 페이지가 같은 쪽 모양을 쓴다. B는 꼬리말에 글이 있고 머리말이 없다
    with_text = '<style:footer><text:p text:style-name="MP1">쪽</text:p></style:footer>'
    masters = _master("A", "Mpm2", _EMPTY_HF) + _master("B", "Mpm2", with_text)
    original = _odt(_content("<text:p>본문</text:p>"), _styles(_layout("Mpm2", footer_height="0.5in"), masters))

    # Act
    fixed, report = fix_hwp_odt(original)

    # Assert: 쪽 여백을 바꾸면 B의 본문 높이까지 바뀌므로 아무것도 고치지 않는다
    assert report.removed_headers_footers == 0
    assert fixed == original


def test_empty_paragraph_right_after_a_table_gets_the_tiny_tail_style():
    content = _content(
        f'{_TABLE}<text:p text:style-name="P37"/><text:p text:style-name="P38">다음 글</text:p>',
        '<style:style style:name="P37" style:family="paragraph">'
        '<style:paragraph-properties fo:line-height="100%"/></style:style>',
    )

    fixed, report = fix_hwp_odt(_odt(content, _styles(_layout("Mpm2"), "")))

    out = _read(fixed, "content.xml")
    assert report.shrunk_table_tails == 1
    assert f'</table:table><text:p text:style-name="{TABLE_TAIL_STYLE}"/>' in out
    assert '<text:p text:style-name="P38">다음 글</text:p>' in out
    tail_style = ET.fromstring(out).find(
        ".//{urn:oasis:names:tc:opendocument:xmlns:style:1.0}style"
        f"[@{{urn:oasis:names:tc:opendocument:xmlns:style:1.0}}name='{TABLE_TAIL_STYLE}']"
    )
    assert tail_style is not None


def test_table_tail_that_breaks_the_page_is_kept():
    content = _content(
        f'{_TABLE}<text:p text:style-name="P9"/>',
        '<style:style style:name="P9" style:family="paragraph">'
        '<style:paragraph-properties fo:break-before="page"/></style:style>',
    )

    fixed, report = fix_hwp_odt(_odt(content, _styles(_layout("Mpm2"), "")))

    assert report.shrunk_table_tails == 0
    assert '<text:p text:style-name="P9"/>' in _read(fixed, "content.xml")


def test_table_tail_that_inherits_a_page_break_from_its_common_style_is_kept():
    # Arrange: 자동 모양 P5 는 쪽 넘김을 공용 모양(styles.xml)에서 물려받는다
    content = _content(
        f'{_TABLE}<text:p text:style-name="P5"/>',
        '<style:style style:name="P5" style:family="paragraph" style:parent-style-name="HwpBreak"/>',
    )
    styles = _styles(_layout("Mpm2"), "").replace(
        "<office:automatic-styles>",
        '<office:styles><style:style style:name="HwpBreak" style:family="paragraph">'
        '<style:paragraph-properties fo:break-before="page"/></style:style></office:styles>'
        "<office:automatic-styles>",
    )

    # Act
    _fixed, report = fix_hwp_odt(_odt(content, styles))

    # Assert
    assert report.shrunk_table_tails == 0


def test_hidden_header_is_left_alone_because_it_takes_no_room():
    hidden = '<style:header style:display="false"/>' + '<style:footer><text:p text:style-name="MP1"/></style:footer>'
    styles = _styles(_layout("Mpm2", footer_height="0.5in"), _master("HWP", "Mpm2", hidden))

    fixed, report = fix_hwp_odt(_odt(_content("<text:p>본문</text:p>"), styles))

    out = _read(fixed, "styles.xml")
    assert report.removed_headers_footers == 1
    assert '<style:header style:display="false"/>' in out and "<style:footer>" not in out
    assert 'fo:margin-top="0.7in"' in out and 'fo:margin-bottom="1.0000in"' in out


def test_nothing_to_fix_returns_the_same_bytes():
    original = _odt(_content(f'{_TABLE}<text:p text:style-name="P37">글</text:p>'), _styles(_layout("Mpm2"), ""))

    fixed, report = fix_hwp_odt(original)

    assert report == OdtFixReport(removed_headers_footers=0, shrunk_table_tails=0)
    assert fixed == original


def test_fixed_odt_keeps_mimetype_first_and_uncompressed_and_other_parts_intact():
    styles = _styles(_layout("Mpm2"), _master("HWP", "Mpm2", _EMPTY_HF))

    fixed, _ = fix_hwp_odt(_odt(_content(f'{_TABLE}<text:p text:style-name="P1"/>'), styles))

    with zipfile.ZipFile(io.BytesIO(fixed)) as z:
        first = z.infolist()[0]
        assert first.filename == "mimetype" and first.compress_type == zipfile.ZIP_STORED
        assert z.read("Pictures/a.png") == b"\x89PNG"
        # 고친 XML도 잘 짜인 XML이다
        ET.fromstring(z.read("content.xml"))
        ET.fromstring(z.read("styles.xml"))
