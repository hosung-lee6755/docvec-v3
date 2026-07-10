"""Real-PDF previews for formats the browser can't render natively.

PDF is displayed directly via the browser's built-in viewer. DOCX converts to
PDF natively via LibreOffice headless. HWP/HWPX have no LibreOffice import
filter (Hancom proprietary formats), so they're first rendered to the existing
best-effort HTML (text order, tables — not pixel-faithful), then that HTML is
converted to PDF via the same LibreOffice binary (Writer can import HTML).
If LibreOffice conversion fails for any reason, falls back to serving the
HTML preview directly. Results are cached in the artifacts bucket as
preview/{document_id}.pdf or .html and served via presigned URL so an
<iframe> can load them without an Authorization header.
"""

import io
import logging
import subprocess
import tempfile
from pathlib import Path

from app.core.config import settings
from app.services.storage import storage_service

logger = logging.getLogger(__name__)

_SOFFICE_TIMEOUT_SECONDS = 120

_HTML_WRAP = (
    '<!doctype html><html><head><meta charset="utf-8">'
    "<style>body{{font-family:sans-serif;line-height:1.6;padding:16px;max-width:900px;margin:0 auto}}"
    "table{{border-collapse:collapse;margin:8px 0}}td,th{{border:1px solid #cbd5e1;padding:4px 8px;font-size:13px}}"
    "img{{max-width:100%}}</style></head><body>{body}</body></html>"
)


def _docx_to_html(raw: bytes) -> str:
    import mammoth

    result = mammoth.convert_to_html(io.BytesIO(raw))
    return _HTML_WRAP.format(body=result.value)


def _hwp_to_html(raw: bytes) -> str:
    from hwp5.hwp5html import HTMLTransform
    from hwp5.xmlmodel import Hwp5File

    with tempfile.NamedTemporaryFile(suffix=".hwp", delete=False) as tmp:
        tmp.write(raw)
        tmp_path = Path(tmp.name)
    try:
        transform = HTMLTransform()
        xhtml_buf, css_buf = io.BytesIO(), io.BytesIO()
        # Hwp5File is single-pass per transform — open once per output.
        transform.transform_hwp5_to_xhtml(Hwp5File(str(tmp_path)), xhtml_buf)
        transform.transform_hwp5_to_css(Hwp5File(str(tmp_path)), css_buf)
    finally:
        tmp_path.unlink(missing_ok=True)

    xhtml = xhtml_buf.getvalue().decode("utf-8", errors="replace")
    css = css_buf.getvalue().decode("utf-8", errors="replace")
    style = f"<style>{css}</style>"
    if "<head>" in xhtml:
        return xhtml.replace("<head>", f"<head><meta charset=\"utf-8\">{style}", 1)
    return _HTML_WRAP.format(body=style + xhtml)


def _hwpx_to_html(raw: bytes) -> str:
    """Document-order render of HWPX paragraphs/tables — layout is simplified,
    but reading order and table structure match the original."""
    import html as html_mod
    import xml.etree.ElementTree as ET
    import zipfile

    from app.pipeline.adapters.hwp_adapter import (
        _collect_nested_hwpx_tables,
        _hwpx_collect_text,
        _hwpx_local_tag,
        _hwpx_table_rows,
    )

    parts: list[str] = []

    def rows_to_html(rows: list[list[str]]) -> str:
        rows_html = [
            f"<tr>{''.join(f'<td>{html_mod.escape(cell)}</td>' for cell in row)}</tr>"
            for row in rows
        ]
        return f"<table>{''.join(rows_html)}</table>"

    def walk(elem) -> None:
        tag = _hwpx_local_tag(elem)
        if tag == "tbl":
            parts.append(rows_to_html(_hwpx_table_rows(elem)))
            return
        if tag == "p":
            # Table is anchored inline inside the paragraph's run
            # (hp:p > hp:run > hp:tbl) — collect the paragraph's own text
            # first, then still search its children for the nested table.
            text = _hwpx_collect_text(elem, skip_tables=True).strip()
            if text:
                parts.append(f"<p>{html_mod.escape(text)}</p>")
            nested_tables: list[list[list[str]]] = []
            _collect_nested_hwpx_tables(elem, nested_tables)
            for rows in nested_tables:
                parts.append(rows_to_html(rows))
            return
        for child in elem:
            walk(child)

    with zipfile.ZipFile(io.BytesIO(raw), "r") as z:
        for name in sorted(z.namelist()):
            if name.startswith("Contents/") and name.endswith(".xml"):
                with z.open(name) as f:
                    walk(ET.parse(f).getroot())

    return _HTML_WRAP.format(body="".join(parts))


def _soffice_to_pdf(raw: bytes, suffix: str) -> bytes:
    """Runs `soffice --headless --convert-to pdf` in an isolated profile dir
    (required so concurrent conversions don't collide over the LibreOffice
    user profile lock) and returns the resulting PDF bytes."""
    with tempfile.TemporaryDirectory() as workdir:
        work = Path(workdir)
        input_path = work / f"input{suffix}"
        input_path.write_bytes(raw)
        profile_dir = work / "profile"
        result = subprocess.run(
            [
                "soffice",
                "--headless",
                "--norestore",
                "--nolockcheck",
                f"-env:UserInstallation=file://{profile_dir}",
                "--convert-to",
                "pdf",
                "--outdir",
                str(work),
                str(input_path),
            ],
            capture_output=True,
            timeout=_SOFFICE_TIMEOUT_SECONDS,
            check=False,
        )
        pdf_path = work / "input.pdf"
        if result.returncode != 0 or not pdf_path.exists():
            stderr = result.stderr.decode("utf-8", errors="replace")
            raise RuntimeError(f"LibreOffice conversion failed: {stderr[:500]}")
        return pdf_path.read_bytes()


def _docx_to_pdf(raw: bytes) -> bytes:
    return _soffice_to_pdf(raw, ".docx")


def _hwp_to_pdf(raw: bytes) -> bytes:
    return _soffice_to_pdf(_hwp_to_html(raw).encode("utf-8"), ".html")


def _hwpx_to_pdf(raw: bytes) -> bytes:
    return _soffice_to_pdf(_hwpx_to_html(raw).encode("utf-8"), ".html")


_PDF_CONVERTERS = {
    ".docx": _docx_to_pdf,
    ".hwp": _hwp_to_pdf,
    ".hwpx": _hwpx_to_pdf,
}

_HTML_CONVERTERS = {
    ".docx": _docx_to_html,
    ".hwp": _hwp_to_html,
    ".hwpx": _hwpx_to_html,
}


def _generate_preview(suffix: str, raw: bytes) -> tuple[bytes, str, str]:
    """Returns (content, kind, content_type). Prefers a real PDF via
    LibreOffice; falls back to the HTML preview if conversion fails
    (e.g. a malformed source file LibreOffice can't open)."""
    pdf_converter = _PDF_CONVERTERS.get(suffix)
    if pdf_converter is not None:
        try:
            return pdf_converter(raw), "pdf", "application/pdf"
        except Exception:
            logger.exception("LibreOffice PDF conversion failed for %s; falling back to HTML", suffix)

    html_converter = _HTML_CONVERTERS.get(suffix)
    if html_converter is not None:
        return html_converter(raw).encode("utf-8"), "html", "text/html; charset=utf-8"

    raise ValueError(f"no preview converter for suffix {suffix}")


def _is_approximate(suffix: str, kind: str) -> bool:
    """DOCX converts straight from the original file via LibreOffice's native
    import — a genuine reproduction. HWP/HWPX have no native import filter,
    so their PDF is built from our own paragraph/table extraction and is a
    reconstruction, not the original layout. Any HTML fallback is likewise
    an approximation regardless of format."""
    return not (suffix == ".docx" and kind == "pdf")


def pdf_pages_text_for(document_id: str) -> list[dict] | None:
    """Extracts per-page text directly from the cached preview PDF, when one
    exists. DOCX/HWP/HWPX have no real page boundaries of their own — the
    generated PDF's pagination is the only page structure available, so this
    (not Document.page_map) is what page-syncs the 원문 대조 tab for those
    formats. Returns None if no PDF preview is cached yet."""
    import fitz

    cache_key = f"preview/{document_id}.pdf"
    try:
        data = storage_service.download_file(settings.minio_bucket_artifacts, cache_key)
    except Exception:
        return None
    doc = fitz.open(stream=data, filetype="pdf")
    try:
        return [{"page_number": i + 1, "text": doc[i].get_text()} for i in range(doc.page_count)]
    finally:
        doc.close()


def preview_url_for(
    document_id: str, filename: str, minio_key: str
) -> tuple[str, str, bool] | tuple[None, None, None]:
    """Returns (presigned_url, kind, approximate) for the converted preview,
    generating and caching it on first request. (None, None, None) when the
    format has no converter. kind is "pdf" or "html"; approximate is True
    when the result is a reconstruction rather than a genuine original
    rendering (see _is_approximate)."""
    suffix = Path(filename).suffix.lower()
    if suffix not in _PDF_CONVERTERS and suffix not in _HTML_CONVERTERS:
        return None, None, None

    for kind, ext, _content_type in (
        ("pdf", "pdf", "application/pdf"),
        ("html", "html", "text/html; charset=utf-8"),
    ):
        cache_key = f"preview/{document_id}.{ext}"
        try:
            storage_service.download_file(settings.minio_bucket_artifacts, cache_key)
        except Exception:
            continue
        url = storage_service.get_presigned_url(settings.minio_bucket_artifacts, cache_key)
        return url, kind, _is_approximate(suffix, kind)

    raw = storage_service.download_file(settings.minio_bucket_originals, minio_key)
    content, kind, content_type = _generate_preview(suffix, raw)
    cache_key = f"preview/{document_id}.{kind}"
    storage_service.upload_file(settings.minio_bucket_artifacts, cache_key, content, content_type)
    url = storage_service.get_presigned_url(settings.minio_bucket_artifacts, cache_key)
    return url, kind, _is_approximate(suffix, kind)
