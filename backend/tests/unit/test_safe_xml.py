"""신뢰할 수 없는 XML 파싱 안전장치(app/core/safe_xml.py)와 HWPX 어댑터 연동."""
import io
import zipfile

import pytest

from app.core import safe_xml
from app.core.safe_xml import UnsafeXMLError, parse_xml, parse_xml_bytes

BILLION_LAUGHS = b"""<?xml version="1.0"?>
<!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">]>
<root>&lol2;</root>"""


def test_parses_plain_document_xml():
    root = parse_xml_bytes("<hp:p xmlns:hp='urn:x'><hp:t>안녕</hp:t></hp:p>".encode())
    assert root[0].text == "안녕"


def test_rejects_entity_declarations():
    with pytest.raises(UnsafeXMLError):
        parse_xml_bytes(BILLION_LAUGHS)


def test_rejects_doctype_even_without_entities():
    with pytest.raises(UnsafeXMLError):
        parse_xml_bytes(b'<!DOCTYPE r SYSTEM "http://evil/x.dtd"><r/>')


def test_rejects_oversized_xml(monkeypatch):
    monkeypatch.setattr(safe_xml, "MAX_XML_BYTES", 10)
    with pytest.raises(UnsafeXMLError):
        parse_xml(io.BytesIO(b"<r>" + b"a" * 50 + b"</r>"))


def test_hwpx_with_entity_bomb_is_reported_as_failed_extraction_not_expanded(tmp_path):
    from app.pipeline.adapters.hwp_adapter import HWPAdapter

    path = tmp_path / "bomb.hwpx"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("Contents/section0.xml", BILLION_LAUGHS)

    parsed = HWPAdapter().extract(path, {})

    assert parsed.page_count == 0
    assert parsed.warnings
