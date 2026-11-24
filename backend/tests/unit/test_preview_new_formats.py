"""새 형식의 원문 미리보기(전체 점검 1-2)."""
import io

import pytest
from PIL import Image

from app.services import preview_service as ps


def test_text_preview_is_escaped_and_not_marked_approximate():
    content, kind, content_type, _approximate = ps._generate_preview(".txt", "<script>x</script> 본문".encode("cp949"))

    assert kind == "html" and content_type.startswith("text/html")
    assert b"<script>x" not in content and "&lt;script&gt;x&lt;/script&gt; 본문" in content.decode("utf-8")
    assert ps._is_approximate(".txt", "html") is False and ps._is_approximate(".md", "html") is False


def _soffice_unavailable(raw, suffix):
    raise RuntimeError("no soffice")


def test_uploaded_html_preview_never_carries_its_scripts_or_handlers(monkeypatch):
    # LibreOffice로 원본을 못 그리면 추출한 글로 다시 적은 HTML 미리보기로 내려간다
    monkeypatch.setattr(ps, "_soffice_to_pdf", _soffice_unavailable)
    raw = b'<h1>T</h1><p onclick="steal()">body<script>steal()</script></p><img src=x onerror=steal()>'

    content, kind, _, approximate = ps._generate_preview(".html", raw)

    text = content.decode("utf-8")
    assert kind == "html" and "<h3>T</h3>" in text and "body" in text
    assert "steal" not in text and "onerror" not in text
    assert approximate is True and ps._is_approximate(".html", "html") is True


def test_uploaded_html_original_is_rendered_without_scripts_or_remote_resources(monkeypatch):
    seen = {}

    def soffice(raw, suffix):
        seen.update(html=raw.decode("utf-8"), suffix=suffix)
        return b"%PDF"

    monkeypatch.setattr(ps, "_soffice_to_pdf", soffice)
    raw = b'<table><tr><td colspan="2">t</td></tr></table><script>x()</script><img src="http://10.0.0.1/a.png">'

    assert ps._generate_preview(".html", raw) == (b"%PDF", "pdf", "application/pdf", False)
    assert seen["suffix"] == ".html" and 'colspan="2"' in seen["html"]
    assert "<script" not in seen["html"] and "10.0.0.1" not in seen["html"]


def test_image_preview_is_a_pdf():
    buffer = io.BytesIO()
    Image.new("RGB", (30, 30), "blue").save(buffer, "PNG")

    content, kind, content_type, _approximate = ps._generate_preview(".png", buffer.getvalue())

    assert (kind, content_type) == ("pdf", "application/pdf") and content.startswith(b"%PDF-")
    assert ps._is_approximate(".png", "pdf") is False


def test_csv_preview_is_an_html_table_without_libreoffice(monkeypatch):
    monkeypatch.setattr(ps, "_soffice_to_pdf", lambda raw, suffix: pytest.fail("CSV must not go through LibreOffice"))

    content, kind, content_type, _approximate = ps._generate_preview(".csv", "이름,부서\n홍길동,<총무>\n".encode("cp949"))

    html = content.decode("utf-8")
    assert kind == "html" and content_type.startswith("text/html")
    assert "<table>" in html and "<td>홍길동</td>" in html and "&lt;총무&gt;" in html
    assert ps._is_approximate(".csv", "html") is False


def test_office_formats_use_libreoffice_and_keep_old_rules(monkeypatch):
    calls = []
    monkeypatch.setattr(ps, "_soffice_to_pdf", lambda raw, suffix: calls.append(suffix) or b"%PDF-1")

    for suffix in (".xlsx", ".pptx"):
        assert ps._generate_preview(suffix, b"x")[1] == "pdf"

    assert calls == [".xlsx", ".pptx"]
    assert ps._is_approximate(".docx", "pdf") is False and ps._is_approximate(".hwp", "pdf") is False
    assert ps._is_approximate(".docx", "html") is True
