"""업로드 파일(HWPX 등)에서 꺼낸 XML을 안전하게 파싱한다.

사용자가 올린 압축 파일 안의 XML은 신뢰할 수 없는 입력이다. 표준 `xml.etree`는
DOCTYPE/ENTITY 선언을 그대로 처리하므로 엔티티 확장(billion laughs)과 압축 폭탄으로
메모리를 고갈시킬 수 있다. 문서 XML(HWPX Contents/*.xml)에는 DOCTYPE/ENTITY가 필요 없으므로
선언이 있으면 거부하고, 읽는 크기에도 상한을 둔다.
"""
import xml.etree.ElementTree as ET
from typing import BinaryIO

MAX_XML_BYTES = 64 * 1024 * 1024
_FORBIDDEN_DECLARATIONS = (b"<!DOCTYPE", b"<!ENTITY")


class UnsafeXMLError(ValueError):
    """DOCTYPE/ENTITY 선언이 있거나 크기 상한을 넘는 XML."""


def parse_xml_bytes(data: bytes) -> ET.Element:
    if len(data) > MAX_XML_BYTES:
        raise UnsafeXMLError(f"XML이 허용 크기({MAX_XML_BYTES}바이트)를 초과합니다.")
    if any(token in data for token in _FORBIDDEN_DECLARATIONS):
        raise UnsafeXMLError("DOCTYPE/ENTITY 선언이 포함된 XML은 처리하지 않습니다.")
    return ET.fromstring(data)


def parse_xml(stream: BinaryIO) -> ET.Element:
    """스트림을 상한까지만 읽어 파싱한다(압축 폭탄이 메모리를 채우지 못하게)."""
    return parse_xml_bytes(stream.read(MAX_XML_BYTES + 1))
