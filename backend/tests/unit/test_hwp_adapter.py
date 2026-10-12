"""Coverage for app.pipeline.adapters.hwp_adapter.

HWPX is exercised with real (tiny, synthetic) zip/XML inputs. Binary .hwp
parsing is exercised by faking pyhwp's Hwp5File (it emits the XML model that
_walk_hwp_body consumes) and olefile's OLE container."""

import io
import zlib
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch
from xml.etree import ElementTree as ET

import pytest

from app.pipeline.adapters import hwp_adapter as hwp
from app.pipeline.adapters.hwp_adapter import HWPAdapter

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20
JPG = b"\xff\xd8\xff" + b"1" * 20

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"


def _hp(xml_body: str) -> str:
    return f'<hs:sec xmlns:hs="urn:s" xmlns:hp="{HP}">{xml_body}</hs:sec>'


def _p(text: str) -> str:
    return f"<hp:p><hp:run><hp:t>{text}</hp:t></hp:run></hp:p>"


def _tbl(*rows: list[str]) -> str:
    trs = "".join(
        "<hp:tr>" + "".join(f"<hp:tc>{_p(c)}</hp:tc>" for c in row) + "</hp:tr>" for row in rows
    )
    return f"<hp:tbl>{trs}</hp:tbl>"


def _write_hwpx(path: Path, sections: dict[str, str], extra: dict[str, bytes] | None = None):
    with zipfile.ZipFile(path, "w") as z:
        for name, xml in sections.items():
            z.writestr(name, xml)
        for name, data in (extra or {}).items():
            z.writestr(name, data)


# ----------------------------------------------------------- tiny helpers


@pytest.mark.parametrize("data,expected", [
    (PNG, True), (JPG, True), (b"BMxxxx", True), (b"GIF89a", True),
    (b"II*\x00zz", True), (b"MM\x00*zz", True), (b"plain", False), (b"", False),
])
def test_looks_like_image_detects_known_magic_bytes(data, expected):
    assert hwp._looks_like_image(data) is expected


def test_local_tag_strips_namespace():
    assert hwp._hwpx_local_tag(ET.fromstring(f'<a:p xmlns:a="{HP}"/>')) == "p"
    assert hwp._hwpx_local_tag(ET.fromstring("<plain/>")) == "plain"


def test_hwpx_collect_text_with_and_without_table_skipping():
    root = ET.fromstring(_hp(
        f"<hp:p><hp:run><hp:t>앞</hp:t>{_tbl(['셀'])}<hp:t>뒤</hp:t></hp:run></hp:p>"
    ))
    para = root[0]

    assert hwp._hwpx_collect_text(para) == "앞셀뒤"
    assert hwp._hwpx_collect_text(para, skip_tables=True) == "앞뒤"


def test_hwpx_collect_text_handles_empty_t_element():
    root = ET.fromstring(_hp("<hp:p><hp:t/></hp:p>"))

    assert hwp._hwpx_collect_text(root[0]) == ""
    assert hwp._hwpx_collect_text(root[0], skip_tables=True) == ""


def test_hwpx_table_rows_skips_non_rows_and_blank_rows():
    root = ET.fromstring(_hp(
        f"<hp:tbl><hp:sz/>"
        f"<hp:tr><hp:tc>{_p(' A ')}</hp:tc><hp:tc>{_p('B')}</hp:tc></hp:tr>"
        f"<hp:tr><hp:tc>{_p('  ')}</hp:tc></hp:tr></hp:tbl>"
    ))

    assert hwp._hwpx_table_rows(root[0]) == [["A", "B"]]


def test_collect_nested_tables_finds_inline_tables_and_ignores_empty_ones():
    root = ET.fromstring(_hp(
        f"<hp:p><hp:run>{_tbl(['x', 'y'])}</hp:run><hp:run><hp:tbl/></hp:run></hp:p>"
    ))
    found: list = []

    hwp._collect_nested_hwpx_tables(root[0], found)

    assert found == [[["x", "y"]]]


def test_walk_hwpx_separates_paragraphs_and_tables_without_double_counting():
    root = ET.fromstring(_hp(
        _p("첫 문단")
        + f"<hp:p><hp:run>{_tbl(['가', '나'])}</hp:run></hp:p>"
        + _tbl(["최상위"])
        + _p("   ")
    ))
    paragraphs, tables = [], []

    hwp._walk_hwpx(root, paragraphs, tables)

    assert paragraphs == ["첫 문단"]
    assert tables == [[["가", "나"]], [["최상위"]]]


# ------------------------------------------------------------- pyhwp walker


def _hwp_xml(body: str) -> ET.Element:
    return ET.fromstring(f"<BodyText>{body}</BodyText>")


def _hwp_p(text: str, inner: str = "") -> str:
    return f"<Paragraph><LineSeg><Text>{text}</Text>{inner}</LineSeg></Paragraph>"


def _hwp_cell(*texts: str) -> str:
    return "<TableCell>" + "".join(_hwp_p(t) for t in texts) + "</TableCell>"


def test_walk_hwp_body_collects_paragraphs_and_anchored_tables_once():
    table = (
        "<TableControl><TableBody>"
        f"<TableRow>{_hwp_cell('이름')}{_hwp_cell('값', '둘째줄')}</TableRow>"
        f"<TableRow>{_hwp_cell('')}</TableRow>"
        "</TableBody></TableControl>"
    )
    body = _hwp_xml(_hwp_p("본문", inner=table) + _hwp_p("  ") + _hwp_p("끝"))
    paragraphs, tables = [], []

    hwp._walk_hwp_body(body, paragraphs, tables)

    assert paragraphs == ["본문", "끝"]  # table cell text is not folded into the host paragraph
    assert tables == [[["이름", "값 둘째줄"]]]


def test_walk_hwp_body_reads_table_caption_and_skips_shape_objects():
    body = _hwp_xml(
        "<TableControl><TableCaption>" + _hwp_p("표 제목") + "</TableCaption>"
        f"<TableBody><TableRow>{_hwp_cell('셀')}</TableRow></TableBody></TableControl>"
        "<GShapeObjectControl>" + _hwp_p("도형 안 글자") + "</GShapeObjectControl>"
    )
    paragraphs, tables = [], []

    hwp._walk_hwp_body(body, paragraphs, tables)

    assert paragraphs == ["표 제목"]
    assert tables == [[["셀"]]]


def test_walk_hwp_body_ignores_table_without_rows_or_body():
    body = _hwp_xml("<TableControl/><TableControl><TableBody><Other/></TableBody></TableControl>")
    paragraphs, tables = [], []

    hwp._walk_hwp_body(body, paragraphs, tables)

    assert paragraphs == [] and tables == []


def test_hwp_collect_text_excludes_nested_controls_but_keeps_other_children():
    para = ET.fromstring(
        "<Paragraph><Text>A</Text><Wrapper><Text>B</Text></Wrapper>"
        "<TableControl><Text>X</Text></TableControl>"
        "<GShapeObjectControl><Text>Y</Text></GShapeObjectControl><Text/></Paragraph>"
    )

    assert hwp._hwp_collect_text(para) == "AB"


# ---------------------------------------------------------- image helpers


def test_hwpx_bindata_images_picks_image_entries_in_sorted_order():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("BinData/b.PNG", b"B")
        z.writestr("BinData/a.jpg", b"A")
        z.writestr("BinData/notes.txt", b"T")
        z.writestr("Contents/x.png", b"NOT-BINDATA")
    with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as z:
        assert hwp._hwpx_bindata_images(z) == [b"A", b"B"]


def _raw_deflate(data: bytes) -> bytes:
    comp = zlib.compressobj(wbits=-15)
    return comp.compress(data) + comp.flush()


def _fake_ole(streams: dict[tuple[str, ...], bytes]):
    ole = MagicMock()
    ole.listdir.return_value = list(streams)
    ole.openstream.side_effect = lambda entry: io.BytesIO(streams[tuple(entry)])
    module = MagicMock()
    module.OleFileIO.return_value = ole
    return module, ole


def test_hwp_bindata_images_handles_raw_compressed_and_junk_streams():
    streams = {
        ("BinData", "BIN0001.png"): PNG,
        ("BinData", "BIN0002.jpg"): _raw_deflate(JPG),
        ("BinData", "BIN0003.bmp"): b"garbage-not-compressed-nor-image",
        ("BinData", "BIN0004.gif"): _raw_deflate(b"compressed but not an image"),
        ("BinData", "BIN0005.dat"): PNG,          # wrong suffix
        ("BodyText", "Section0"): b"x",            # wrong storage
        ("BinData", "sub", "BIN0006.png"): PNG,    # wrong depth
    }
    module, ole = _fake_ole(streams)

    with patch.dict("sys.modules", {"olefile": module}):
        images = hwp._hwp_bindata_images("/tmp/x.hwp")

    assert images == [PNG, JPG]
    ole.close.assert_called_once()


def test_hwp_bindata_images_closes_ole_even_when_stream_read_fails():
    module, ole = _fake_ole({("BinData", "a.png"): PNG})
    ole.openstream.side_effect = OSError("corrupt")

    with patch.dict("sys.modules", {"olefile": module}):
        with pytest.raises(OSError):
            hwp._hwp_bindata_images("/tmp/x.hwp")

    ole.close.assert_called_once()


# ----------------------------------------------------------- adapter surface


def test_adapter_identity_and_capabilities():
    adapter = HWPAdapter()

    assert adapter.format_id == "hwp"
    assert adapter.capabilities.native_text and adapter.capabilities.native_table
    assert not adapter.capabilities.ocr_required and not adapter.capabilities.bbox_available


@pytest.mark.parametrize("name,mime,expected", [
    ("a.HWP", "application/octet-stream", True),
    ("a.hwpx", "application/zip", True),
    ("a.bin", "application/x-hwp", True),
    ("a.bin", "application/haansofthwp", True),
    ("a.pdf", "application/pdf", False),
])
def test_can_handle_by_suffix_or_mime(name, mime, expected):
    assert HWPAdapter().can_handle(Path(name), mime) is expected


def test_extract_metadata_returns_path():
    assert HWPAdapter().extract_metadata(Path("a.hwp")) == {"file_path": str(Path("a.hwp"))}


# --------------------------------------------------------------- HWPX extract


def test_extract_hwpx_builds_single_page_with_paragraph_table_and_image_blocks(tmp_path):
    path = tmp_path / "doc.hwpx"
    _write_hwpx(
        path,
        {
            "Contents/section1.xml": _hp(_p("둘째 섹션")),
            "Contents/section0.xml": _hp(_p("첫 섹션") + _tbl(["A", "B"], ["C", "D"])),
            "Contents/content.hpf": "<not-xml-and-not-read",
            "Preview/skip.xml": "<x/>",
        },
        extra={"BinData/image1.png": PNG},
    )

    doc = HWPAdapter().extract(path, {})

    assert doc.format_id == "hwpx" and doc.page_count == 1 and doc.warnings == []
    page = doc.pages[0]
    # sections are read in name order; paragraphs first, then "[표 N]" blocks
    assert [b.text for b in page.text_blocks] == [
        "첫 섹션", "둘째 섹션", "[표 1]\nA | B\nC | D",
    ]
    assert page.text_blocks[2].block_type == "table"
    assert page.table_candidates[0].rows == [["A", "B"], ["C", "D"]]
    assert [r.image_bytes for r in page.image_regions] == [PNG]
    assert (page.width, page.height) == (595, 842)


def test_extract_hwpx_reports_failure_for_corrupt_zip(tmp_path):
    path = tmp_path / "bad.hwpx"
    path.write_bytes(b"this is not a zip")

    doc = HWPAdapter().extract(path, {})

    assert doc.format_id == "hwpx" and doc.pages == [] and doc.page_count == 0
    assert doc.warnings[0].startswith("HWPX extraction failed")


def test_extract_hwpx_rejects_xml_with_entity_declarations(tmp_path):
    path = tmp_path / "evil.hwpx"
    _write_hwpx(path, {"Contents/section0.xml": '<!DOCTYPE x [<!ENTITY a "b">]><x/>'})

    doc = HWPAdapter().extract(path, {})

    assert doc.pages == []
    assert "HWPX extraction failed" in doc.warnings[0]


# ----------------------------------------------------------------- HWP extract


def _fake_hwp5(xml: bytes | Exception):
    module = MagicMock()

    def dump(buf, xml_declaration):
        if isinstance(xml, Exception):
            raise xml
        buf.write(xml)

    module.Hwp5File.return_value.xmlevents.return_value.dump.side_effect = dump
    return {"hwp5": MagicMock(), "hwp5.xmlmodel": module}


def _hwp_doc_xml(body: str) -> bytes:
    return f"<HwpDoc><BodyText>{body}</BodyText></HwpDoc>".encode()


def test_extract_hwp_parses_body_tables_and_embedded_images():
    table = (
        f"<TableControl><TableBody><TableRow>{_hwp_cell('x')}{_hwp_cell('y')}</TableRow>"
        "</TableBody></TableControl>"
    )
    modules = _fake_hwp5(_hwp_doc_xml(_hwp_p("본문", inner=table)))

    with patch.dict("sys.modules", modules), \
         patch.object(hwp, "_hwp_bindata_images", return_value=[PNG]):
        doc = HWPAdapter().extract(Path("a.hwp"), {})

    assert doc.format_id == "hwp" and doc.page_count == 1 and doc.warnings == []
    page = doc.pages[0]
    assert [b.text for b in page.text_blocks] == ["본문", "[표 1]\nx | y"]
    assert page.text_blocks[1].block_type == "table"
    assert page.table_candidates[0].rows == [["x", "y"]]
    assert page.image_regions[0].image_bytes == PNG


def test_extract_hwp_without_bodytext_yields_empty_page():
    modules = _fake_hwp5(b"<HwpDoc/>")

    with patch.dict("sys.modules", modules), \
         patch.object(hwp, "_hwp_bindata_images", return_value=[]):
        doc = HWPAdapter().extract(Path("a.hwp"), {})

    assert doc.pages[0].text_blocks == []


def test_extract_hwp_image_failure_is_a_warning_not_an_error():
    modules = _fake_hwp5(_hwp_doc_xml(_hwp_p("본문")))

    with patch.dict("sys.modules", modules), \
         patch.object(hwp, "_hwp_bindata_images", side_effect=RuntimeError("ole broken")):
        doc = HWPAdapter().extract(Path("a.hwp"), {})

    assert [b.text for b in doc.pages[0].text_blocks] == ["본문"]
    assert doc.warnings == ["HWP image extraction failed: ole broken"]


def test_extract_hwp_parse_failure_returns_empty_document_with_warning():
    modules = _fake_hwp5(RuntimeError("bad header"))

    with patch.dict("sys.modules", modules):
        doc = HWPAdapter().extract(Path("a.hwp"), {})

    assert doc.pages == [] and doc.page_count == 0
    assert doc.warnings == ["HWP extraction failed: bad header"]


def test_extract_hwp_reports_missing_pyhwp_library():
    # a None entry in sys.modules makes `import hwp5...` raise ImportError
    with patch.dict("sys.modules", {"hwp5": None, "hwp5.xmlmodel": None}):
        doc = HWPAdapter().extract(Path("a.hwp"), {})

    assert doc.pages == []
    assert "pyhwp library not installed" in doc.warnings[0]
