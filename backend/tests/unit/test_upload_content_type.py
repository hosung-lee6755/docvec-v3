"""업로드된 원본의 Content-Type 결정.

클라이언트가 타입을 안 보내거나 application/octet-stream으로 보내면(curl, 스크립트, 일부 SDK)
MinIO에 octet-stream으로 저장된다. 브라우저는 X-Content-Type-Options: nosniff 때문에 이 PDF를
iframe 미리보기로 렌더링하지 못해 "원문 대조" 화면의 원본 영역이 통째로 비었다.
파일 확장자로 추정한 타입을 우선 쓰고, 클라이언트가 구체적인 타입을 보냈으면 그것을 존중한다.
"""
import pytest

from app.api.v1.endpoints.documents.upload import _resolve_content_type


@pytest.mark.parametrize("declared", [None, "", "application/octet-stream"])
def test_generic_declared_type_is_replaced_by_the_filename_guess(declared):
    assert _resolve_content_type("보고서.pdf", declared) == "application/pdf"


def test_specific_declared_type_is_respected():
    assert _resolve_content_type("a.pdf", "application/pdf") == "application/pdf"
    assert _resolve_content_type("a.bin", "image/png") == "image/png"


@pytest.mark.parametrize("hostile", ["text/html", "image/svg+xml", "application/xhtml+xml", "text/javascript"])
def test_known_extension_ignores_a_hostile_declared_type(hostile):
    # 원본은 다른 출처(MinIO)에서 인라인으로 렌더링된다. 클라이언트가 .pdf 를 text/html 로 선언해도
    # 저장되는 타입은 확장자 기준이어야 스크립트가 실행되지 않는다.
    assert _resolve_content_type("evil.pdf", hostile) == "application/pdf"
    expected = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    assert _resolve_content_type("evil.docx", hostile) == expected


def test_unknown_extension_falls_back_to_octet_stream():
    assert _resolve_content_type("a.unknownext", None) == "application/octet-stream"


def test_docx_is_recognised_by_extension():
    expected = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    assert _resolve_content_type("제안서.docx", "application/octet-stream") == expected
