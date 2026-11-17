"""새 형식의 원문 미리보기(전체 점검 1-2)."""
import io

from PIL import Image

from app.services import preview_service as ps


def test_text_preview_is_escaped_and_not_marked_approximate():
    content, kind, content_type = ps._generate_preview(".txt", "<script>x</script> 본문".encode("cp949"))

    assert kind == "html" and content_type.startswith("text/html")
    assert b"<script>x" not in content and "&lt;script&gt;x&lt;/script&gt; 본문" in content.decode("utf-8")
    assert ps._is_approximate(".txt", "html") is False and ps._is_approximate(".md", "html") is False


def test_uploaded_html_preview_never_carries_its_scripts_or_handlers():
    raw = b'<h1>T</h1><p onclick="steal()">body<script>steal()</script></p><img src=x onerror=steal()>'

    content, kind, _ = ps._generate_preview(".html", raw)

    text = content.decode("utf-8")
    assert kind == "html" and "<h3>T</h3>" in text and "body" in text
    assert "steal" not in text and "onerror" not in text
    assert ps._is_approximate(".html", "html") is True


def test_image_preview_is_a_pdf():
    buffer = io.BytesIO()
    Image.new("RGB", (30, 30), "blue").save(buffer, "PNG")

    content, kind, content_type = ps._generate_preview(".png", buffer.getvalue())

    assert (kind, content_type) == ("pdf", "application/pdf") and content.startswith(b"%PDF-")
    assert ps._is_approximate(".png", "pdf") is False


def test_office_formats_use_libreoffice_and_keep_old_rules(monkeypatch):
    calls = []
    monkeypatch.setattr(ps, "_soffice_to_pdf", lambda raw, suffix: calls.append(suffix) or b"%PDF-1")

    for suffix in (".xlsx", ".pptx"):
        assert ps._generate_preview(suffix, b"x")[1] == "pdf"

    assert calls == [".xlsx", ".pptx"]
    assert ps._is_approximate(".docx", "pdf") is False and ps._is_approximate(".hwp", "pdf") is True
    assert ps._is_approximate(".docx", "html") is True
