"""Coverage for app.services.preview_service. Format converters run on tiny
real inputs (mammoth/PyMuPDF/zip+XML); LibreOffice, pyhwp and MinIO are faked."""

import io
import zipfile
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.core.config import settings
from app.services import preview_service as ps

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"


# ---------------------------------------------------------------- converters


def _docx_bytes(*paragraphs: str) -> bytes:
    import docx

    document = docx.Document()
    for text in paragraphs:
        document.add_paragraph(text)
    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()


def test_docx_to_html_wraps_converted_body():
    html = ps._docx_to_html(_docx_bytes("안녕 문서"))

    assert html.startswith("<!doctype html>")
    assert "<p>안녕 문서</p>" in html
    assert "border-collapse:collapse" in html  # table CSS survives str.format brace escaping


def _hwpx_zip(sections: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, xml in sections.items():
            z.writestr(name, xml)
    return buf.getvalue()


def _sec(body: str) -> str:
    return f'<hs:sec xmlns:hs="urn:s" xmlns:hp="{HP}">{body}</hs:sec>'


def test_hwpx_to_html_renders_paragraphs_tables_and_escapes_markup():
    nested = (
        "<hp:p><hp:run><hp:tbl><hp:tr><hp:tc><hp:p><hp:run><hp:t>셀1</hp:t></hp:run></hp:p></hp:tc>"
        "<hp:tc><hp:p><hp:run><hp:t>셀2</hp:t></hp:run></hp:p></hp:tc></hp:tr></hp:tbl></hp:run></hp:p>"
    )
    xml = _sec(
        "<hp:p><hp:run><hp:t>&lt;script&gt;alert(1)&lt;/script&gt;</hp:t></hp:run></hp:p>"
        + nested
        + "<hp:p><hp:run><hp:t>  </hp:t></hp:run></hp:p>"
    )

    html = ps._hwpx_to_html(_hwpx_zip({
        "Contents/section0.xml": xml, "Contents/header.txt": "ignored", "other/x.xml": "<x/>",
    }))

    assert "<p>&lt;script&gt;alert(1)&lt;/script&gt;</p>" in html
    assert "<table><tr><td>셀1</td><td>셀2</td></tr></table>" in html
    assert "<script>" not in html
    assert html.count("<p>") == 1  # blank paragraph dropped


def test_hwpx_to_html_top_level_table():
    xml = _sec(
        "<hp:tbl><hp:tr><hp:tc><hp:p><hp:run><hp:t>X</hp:t></hp:run></hp:p></hp:tc></hp:tr></hp:tbl>"
    )

    html = ps._hwpx_to_html(_hwpx_zip({"Contents/section0.xml": xml}))

    assert "<table><tr><td>X</td></tr></table>" in html


def _fake_hwp5(xhtml: str, css: str = "p{color:red}"):
    transform = MagicMock()

    def to_xhtml(_hwp, buf):
        buf.write(xhtml.encode("utf-8"))

    def to_css(_hwp, buf):
        buf.write(css.encode("utf-8"))

    transform.transform_hwp5_to_xhtml.side_effect = to_xhtml
    transform.transform_hwp5_to_css.side_effect = to_css
    html_mod = MagicMock()
    html_mod.HTMLTransform.return_value = transform
    return {"hwp5": MagicMock(), "hwp5.hwp5html": html_mod, "hwp5.xmlmodel": MagicMock()}, transform


def test_hwp_to_html_injects_css_into_existing_head_and_cleans_temp_file():
    modules, _t = _fake_hwp5("<html><head></head><body>본문</body></html>")
    created = []
    real_named = ps.tempfile.NamedTemporaryFile

    def tracking(*a, **k):
        f = real_named(*a, **k)
        created.append(f.name)
        return f

    with patch.dict("sys.modules", modules), patch.object(ps.tempfile, "NamedTemporaryFile", tracking):
        html = ps._hwp_to_html(b"raw-hwp")

    assert '<head><meta charset="utf-8"><style>p{color:red}</style></head>' in html
    assert created and not __import__("os").path.exists(created[0])


def test_hwp_to_html_wraps_fragment_without_head():
    modules, _t = _fake_hwp5("<div>조각</div>")

    with patch.dict("sys.modules", modules):
        html = ps._hwp_to_html(b"raw")

    assert html.startswith("<!doctype html>")
    assert "<style>p{color:red}</style><div>조각</div>" in html


def test_hwp_to_html_removes_temp_file_when_transform_fails():
    modules, transform = _fake_hwp5("x")
    transform.transform_hwp5_to_xhtml.side_effect = RuntimeError("bad hwp")
    created = []
    real_named = ps.tempfile.NamedTemporaryFile

    def tracking(*a, **k):
        f = real_named(*a, **k)
        created.append(f.name)
        return f

    with patch.dict("sys.modules", modules), patch.object(ps.tempfile, "NamedTemporaryFile", tracking):
        with pytest.raises(RuntimeError, match="bad hwp"):
            ps._hwp_to_html(b"raw")

    assert not __import__("os").path.exists(created[0])


# ------------------------------------------------------------- soffice


def _soffice_runner(*, returncode=0, write_pdf=True, stderr=b""):
    captured = {}

    def run(cmd, **kwargs):
        captured["cmd"], captured["kwargs"] = cmd, kwargs
        outdir = cmd[cmd.index("--outdir") + 1]
        captured["input_bytes"] = open(cmd[-1], "rb").read()
        if write_pdf:
            with open(f"{outdir}/input.pdf", "wb") as f:
                f.write(b"%PDF-fake")
        return SimpleNamespace(returncode=returncode, stderr=stderr)

    return run, captured


def test_soffice_to_pdf_runs_isolated_headless_conversion_and_returns_pdf():
    run, captured = _soffice_runner()

    with patch.object(ps.subprocess, "run", side_effect=run):
        pdf = ps._soffice_to_pdf(b"<html/>", ".html")

    assert pdf == b"%PDF-fake"
    cmd = captured["cmd"]
    assert cmd[0] == "soffice" and "--headless" in cmd and "pdf" in cmd
    assert any(a.startswith("-env:UserInstallation=file://") for a in cmd)
    assert cmd[-1].endswith("input.html")
    assert captured["input_bytes"] == b"<html/>"
    assert captured["kwargs"]["timeout"] == ps._SOFFICE_TIMEOUT_SECONDS


def test_soffice_to_pdf_raises_with_stderr_on_nonzero_exit():
    run, _ = _soffice_runner(returncode=1, write_pdf=False, stderr=b"filter failed " + b"x" * 900)

    with patch.object(ps.subprocess, "run", side_effect=run):
        with pytest.raises(RuntimeError) as caught:
            ps._soffice_to_pdf(b"x", ".docx")

    assert "LibreOffice conversion failed: filter failed" in str(caught.value)
    assert len(str(caught.value)) < 600  # stderr is truncated


def test_soffice_to_pdf_raises_when_no_output_file_even_with_zero_exit():
    run, _ = _soffice_runner(returncode=0, write_pdf=False)

    with patch.object(ps.subprocess, "run", side_effect=run):
        with pytest.raises(RuntimeError):
            ps._soffice_to_pdf(b"x", ".docx")


def test_format_specific_pdf_converters_pick_the_right_input_suffix():
    with patch.object(ps, "_soffice_to_pdf", return_value=b"PDF") as soffice, \
         patch.object(ps, "_hwp_to_html", return_value="<hwp/>"), \
         patch.object(ps, "_hwpx_to_html", return_value="<hwpx/>"):
        assert ps._docx_to_pdf(b"d") == b"PDF"
        ps._hwp_to_pdf(b"h")
        ps._hwpx_to_pdf(b"x")

    assert [c.args for c in soffice.call_args_list] == [
        (b"d", ".docx"), (b"<hwp/>", ".html"), (b"<hwpx/>", ".html"),
    ]


# ---------------------------------------------------------- _generate_preview


def test_generate_preview_prefers_pdf():
    with patch.dict(ps._PDF_CONVERTERS, {".docx": lambda raw: b"PDF:" + raw}):
        assert ps._generate_preview(".docx", b"r") == (b"PDF:r", "pdf", "application/pdf")


def test_generate_preview_falls_back_to_html_when_pdf_conversion_fails():
    def broken(_raw):
        raise RuntimeError("soffice crashed")

    with patch.dict(ps._PDF_CONVERTERS, {".docx": broken}), \
         patch.dict(ps._HTML_CONVERTERS, {".docx": lambda raw: "<p>html</p>"}):
        content, kind, ctype = ps._generate_preview(".docx", b"r")

    assert (content, kind, ctype) == (b"<p>html</p>", "html", "text/html; charset=utf-8")


def test_generate_preview_unknown_suffix_raises():
    with pytest.raises(ValueError, match="no preview converter for suffix .xyz"):
        ps._generate_preview(".xyz", b"")


def test_generate_preview_propagates_html_converter_failure():
    def boom(_raw):
        raise RuntimeError("html failed")

    with patch.dict(ps._PDF_CONVERTERS, {}, clear=True), \
         patch.dict(ps._HTML_CONVERTERS, {".docx": boom}):
        with pytest.raises(RuntimeError, match="html failed"):
            ps._generate_preview(".docx", b"")


@pytest.mark.parametrize("suffix,kind,expected", [
    (".docx", "pdf", False),
    (".docx", "html", True),
    (".hwp", "pdf", True),
    (".hwpx", "pdf", True),
    (".hwp", "html", True),
])
def test_is_approximate(suffix, kind, expected):
    assert ps._is_approximate(suffix, kind) is expected


# ----------------------------------------------------------- pdf_pages_text_for


def _pdf_bytes(*page_texts: str) -> bytes:
    import fitz

    doc = fitz.open()
    for text in page_texts:
        page = doc.new_page()
        page.insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


def test_pdf_pages_text_for_extracts_text_per_page_from_cached_pdf():
    storage = MagicMock()
    storage.download_file.return_value = _pdf_bytes("alpha page", "beta page")

    with patch.object(ps, "storage_service", storage):
        pages = ps.pdf_pages_text_for("doc-1")

    storage.download_file.assert_called_once_with(
        settings.minio_bucket_artifacts, "preview/doc-1.pdf"
    )
    assert [p["page_number"] for p in pages] == [1, 2]
    assert "alpha page" in pages[0]["text"] and "beta page" in pages[1]["text"]


def test_pdf_pages_text_for_none_when_not_cached():
    storage = MagicMock()
    storage.download_file.side_effect = RuntimeError("NoSuchKey")

    with patch.object(ps, "storage_service", storage):
        assert ps.pdf_pages_text_for("doc-1") is None


# --------------------------------------------------------------- preview_url_for


@pytest.fixture
def storage():
    mock = MagicMock()
    mock.get_presigned_url.side_effect = lambda bucket, key: f"https://signed/{key}"
    with patch.object(ps, "storage_service", mock):
        yield mock


def test_preview_url_unsupported_format_returns_nones_without_storage_access(storage):
    assert ps.preview_url_for("d", "photo.png", "k") == (None, None, None)
    storage.download_file.assert_not_called()


def test_preview_url_serves_cached_pdf_without_regenerating(storage):
    with patch.object(ps, "_generate_preview") as generate:
        out = ps.preview_url_for("d1", "a.DOCX", "orig/key")

    assert out == ("https://signed/preview/d1.pdf", "pdf", False)
    generate.assert_not_called()
    storage.upload_file.assert_not_called()


def test_preview_url_falls_back_to_cached_html_when_pdf_missing(storage):
    def download(bucket, key):
        if key.endswith(".pdf"):
            raise RuntimeError("missing")
        return b"<html/>"

    storage.download_file.side_effect = download

    out = ps.preview_url_for("d1", "a.docx", "orig/key")

    assert out == ("https://signed/preview/d1.html", "html", True)


def test_preview_url_generates_caches_and_signs_on_first_request(storage):
    def download(bucket, key):
        if bucket == settings.minio_bucket_originals:
            return b"ORIGINAL"
        raise RuntimeError("no cache")

    storage.download_file.side_effect = download

    with patch.object(ps, "_generate_preview",
                      return_value=(b"PDF", "pdf", "application/pdf")) as generate:
        out = ps.preview_url_for("d1", "report.hwpx", "orig/key")

    generate.assert_called_once_with(".hwpx", b"ORIGINAL")
    storage.upload_file.assert_called_once_with(
        settings.minio_bucket_artifacts, "preview/d1.pdf", b"PDF", "application/pdf"
    )
    assert out == ("https://signed/preview/d1.pdf", "pdf", True)


def test_preview_url_html_fallback_result_is_cached_as_html(storage):
    storage.download_file.side_effect = lambda b, k: (
        b"ORIG" if b == settings.minio_bucket_originals else (_ for _ in ()).throw(KeyError(k))
    )

    with patch.object(ps, "_generate_preview",
                      return_value=(b"<p/>", "html", "text/html; charset=utf-8")):
        out = ps.preview_url_for("d1", "a.docx", "k")

    assert storage.upload_file.call_args.args[1] == "preview/d1.html"
    assert out == ("https://signed/preview/d1.html", "html", True)
