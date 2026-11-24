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

    def run(cmd, timeout):
        captured["cmd"], captured["timeout"] = cmd, timeout
        outdir = cmd[cmd.index("--outdir") + 1]
        captured["input_bytes"] = open(cmd[-1], "rb").read()
        if write_pdf:
            with open(f"{outdir}/input.pdf", "wb") as f:
                f.write(b"%PDF-fake")
        return returncode, stderr

    return run, captured


def test_soffice_to_pdf_runs_isolated_headless_conversion_and_returns_pdf():
    run, captured = _soffice_runner()

    with patch.object(ps, "_run_soffice", side_effect=run):
        pdf = ps._soffice_to_pdf(b"<html/>", ".html")

    assert pdf == b"%PDF-fake"
    cmd = captured["cmd"]
    assert cmd[0] == "soffice" and "--headless" in cmd and "pdf" in cmd
    assert any(a.startswith("-env:UserInstallation=file://") for a in cmd)
    assert cmd[-1].endswith("input.html")
    assert captured["input_bytes"] == b"<html/>"
    assert captured["timeout"] == ps._SOFFICE_TIMEOUT_SECONDS


def test_soffice_to_pdf_raises_with_stderr_on_nonzero_exit():
    run, _ = _soffice_runner(returncode=1, write_pdf=False, stderr=b"filter failed " + b"x" * 900)

    with patch.object(ps, "_run_soffice", side_effect=run):
        with pytest.raises(RuntimeError) as caught:
            ps._soffice_to_pdf(b"x", ".docx")

    assert "LibreOffice conversion failed: filter failed" in str(caught.value)
    assert len(str(caught.value)) < 600  # stderr is truncated


def test_soffice_to_pdf_raises_when_no_output_file_even_with_zero_exit():
    run, _ = _soffice_runner(returncode=0, write_pdf=False)

    with patch.object(ps, "_run_soffice", side_effect=run):
        with pytest.raises(RuntimeError):
            ps._soffice_to_pdf(b"x", ".docx")



def _hwp_soffice_runner(*, odt_returncode=0):
    """HWP 원본 변환 흉내. odt 요청이면 ODT(아무 내용)를, pdf 요청이면 입력 파일 이름을 적은 PDF를 쓴다."""
    calls = []

    def run(cmd, timeout):
        target, outdir, source = cmd[cmd.index("--convert-to") + 1], cmd[cmd.index("--outdir") + 1], cmd[-1]
        stem = source.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        calls.append((target, source.rsplit("/", 1)[-1]))
        if target == "odt":
            with open(f"{outdir}/{stem}.odt", "wb") as f:
                f.write(b"odt-from-hwp")
            return odt_returncode, b"crash" if odt_returncode else b""
        with open(f"{outdir}/{stem}.pdf", "wb") as f:
            f.write(f"%PDF-{stem}".encode() + open(source, "rb").read())
        return 0, b""

    return run, calls


def test_hwp_original_is_opened_as_odt_fixed_and_then_drawn():
    run, calls = _hwp_soffice_runner()
    fix = MagicMock(return_value=(b"fixed-odt", SimpleNamespace(removed_headers_footers=2, shrunk_table_tails=19)))

    with patch.object(ps, "_run_soffice", side_effect=run), \
         patch("app.services.preview_odt_fix.fix_hwp_odt", fix):
        pdf = ps._PDF_CONVERTERS[".hwp"](b"raw-hwp")

    assert calls == [("odt", "input.hwp"), ("pdf", "fixed.odt")]
    fix.assert_called_once_with(b"odt-from-hwp")
    assert pdf == b"%PDF-fixedfixed-odt"


def test_hwp_original_falls_back_to_direct_pdf_when_odt_step_fails():
    # ODT 단계가 실패하면(비정상 종료하고 남은 ODT도 온전하지 않으면) 고치지 않고 원본을 바로 그린다
    run, calls = _hwp_soffice_runner(odt_returncode=134)

    with patch.object(ps, "_run_soffice", side_effect=run):
        pdf = ps._PDF_CONVERTERS[".hwpx"](b"raw-hwpx")

    assert calls == [("odt", "input.hwpx"), ("pdf", "input.hwpx")]
    assert pdf == b"%PDF-inputraw-hwpx"


def test_hwp_original_does_not_retry_directly_after_the_odt_step_times_out():
    # 원본을 여는 데 시간을 다 썼으면 바로 PDF로 다시 그려도 같은 시간이 걸린다. 재구성 미리보기로 넘긴다
    calls = []

    def run(cmd, timeout):
        calls.append(cmd[cmd.index("--convert-to") + 1])
        raise ps.SofficeTimeoutError("LibreOffice conversion timed out after 300s")

    with patch.object(ps, "_run_soffice", side_effect=run), pytest.raises(ps.SofficeTimeoutError):
        ps._PDF_CONVERTERS[".hwp"](b"raw-hwp")

    assert calls == ["odt"]


def _complete_odt() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as odt:
        odt.writestr("mimetype", "application/vnd.oasis.opendocument.text")
        odt.writestr("content.xml", "<c/>")
        odt.writestr("styles.xml", "<s/>")
    return buffer.getvalue()


@pytest.mark.parametrize(
    ("target", "written", "accepted"),
    [
        ("pdf", b"%PDF-1.7\n...\n%%EOF\n", True),
        ("pdf", b"%PDF-1.7\n...truncated", False),
        ("odt", None, True),  # _complete_odt()
        ("odt", b"PK\x03\x04broken", False),
    ],
)
def test_crashed_conversion_is_used_only_when_its_output_is_complete(tmp_path, target, written, accepted):
    # H2Orestart를 쓴 변환은 결과를 다 쓴 뒤 끝내는 중에 rc=134로 죽을 때가 있다. 그 결과가 온전하면 쓴다
    data = _complete_odt() if written is None else written
    source = tmp_path / "input.hwp"
    source.write_bytes(b"raw")

    def run(cmd, timeout):
        (tmp_path / f"input.{target}").write_bytes(data)
        return 134, b"Unspecified Application Error"

    with patch.object(ps, "_run_soffice", side_effect=run):
        if accepted:
            assert ps._soffice_convert(source, target).read_bytes() == data
        else:
            with pytest.raises(RuntimeError, match="LibreOffice conversion failed"):
                ps._soffice_convert(source, target)


def test_run_soffice_kills_the_whole_process_group_on_timeout():
    # soffice는 셸 스크립트라 실제 변환은 손자 프로세스가 한다. 시간을 넘기면 그룹 전체를 끝내야 남지 않는다
    process = MagicMock(pid=4321)
    process.communicate.side_effect = [ps.subprocess.TimeoutExpired("soffice", 1), (b"", b"")]
    with patch.object(ps.subprocess, "Popen", return_value=process) as popen,          patch.object(ps.os, "killpg") as killpg:
        with pytest.raises(RuntimeError, match="timed out"):
            ps._run_soffice(["soffice"], 1)

    assert popen.call_args.kwargs["start_new_session"] is True
    killpg.assert_called_once_with(4321, ps.signal.SIGKILL)


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
        assert ps._generate_preview(".docx", b"r") == (b"PDF:r", "pdf", "application/pdf", False)


def test_generate_preview_falls_back_to_html_when_pdf_conversion_fails():
    def broken(_raw):
        raise RuntimeError("soffice crashed")

    with patch.dict(ps._PDF_CONVERTERS, {".docx": broken}), \
         patch.dict(ps._HTML_CONVERTERS, {".docx": lambda raw: "<p>html</p>"}):
        result = ps._generate_preview(".docx", b"r")

    assert result == (b"<p>html</p>", "html", "text/html; charset=utf-8", True)


def test_hwp_original_is_converted_directly_through_libreoffice():
    # 원본을 H2Orestart로 열어 쪽 나눔을 고친 뒤 그린다(_hwp_original_to_pdf). 결과는 원본 그대로인 미리보기다
    with patch.object(ps, "_hwp_original_to_pdf", return_value=b"%PDF") as original:
        assert ps._generate_preview(".hwpx", b"orig") == (b"%PDF", "pdf", "application/pdf", False)

    original.assert_called_once_with(b"orig", ".hwpx")


def test_hwp_falls_back_to_a_reconstructed_pdf_marked_approximate_when_the_original_cannot_be_opened():
    # H2Orestart 확장이 없거나 원본을 못 읽으면 예전처럼 우리가 읽은 글로 다시 만든 PDF를 쓴다
    def broken(_raw):
        raise RuntimeError("source file could not be loaded")

    with patch.dict(ps._PDF_CONVERTERS, {".hwp": broken}), \
         patch.dict(ps._RECONSTRUCTED_PDF_CONVERTERS, {".hwp": lambda raw: b"REBUILT"}):
        assert ps._generate_preview(".hwp", b"r") == (b"REBUILT", "pdf", "application/pdf", True)


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
    (".hwp", "pdf", False),
    (".hwpx", "pdf", False),
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
        settings.minio_bucket_artifacts, "preview/v2/doc-1.pdf"
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
    assert ps.preview_url_for("d", "data.rtf", "k") == (None, None, None)
    storage.download_file.assert_not_called()


def test_preview_url_serves_cached_pdf_without_regenerating(storage):
    def download(bucket, key):
        if key.endswith(".approximate"):
            raise RuntimeError("missing")
        return b"%PDF"

    storage.download_file.side_effect = download
    with patch.object(ps, "_generate_preview") as generate:
        out = ps.preview_url_for("d1", "a.DOCX", "orig/key")

    assert out == ("https://signed/preview/v2/d1.pdf", "pdf", False)
    generate.assert_not_called()
    storage.upload_file.assert_not_called()


def test_preview_url_falls_back_to_cached_html_when_pdf_missing(storage):
    def download(bucket, key):
        if key.endswith(".pdf"):
            raise RuntimeError("missing")
        return b"<html/>"

    storage.download_file.side_effect = download

    out = ps.preview_url_for("d1", "a.docx", "orig/key")

    assert out == ("https://signed/preview/v2/d1.html", "html", True)


def test_preview_url_generates_caches_and_signs_on_first_request(storage):
    def download(bucket, key):
        if bucket == settings.minio_bucket_originals:
            return b"ORIGINAL"
        raise RuntimeError("no cache")

    storage.download_file.side_effect = download

    with patch.object(ps, "_generate_preview",
                      return_value=(b"PDF", "pdf", "application/pdf", True)) as generate:
        out = ps.preview_url_for("d1", "report.hwpx", "orig/key")

    generate.assert_called_once_with(".hwpx", b"ORIGINAL")
    # 재구성 PDF로 내려갔으므로 PDF와 함께 "원본과 다를 수 있음" 표시를 남긴다
    uploaded = [c.args[1] for c in storage.upload_file.call_args_list]
    assert uploaded == ["preview/v2/d1.pdf", "preview/v2/d1.approximate"]
    assert out == ("https://signed/preview/v2/d1.pdf", "pdf", True)


def test_faithful_hwp_preview_is_not_marked_and_reads_as_original(storage):
    cached: dict = {}

    def download(bucket, key):
        if bucket == settings.minio_bucket_originals:
            return b"ORIGINAL"
        if key in cached:
            return cached[key]
        raise RuntimeError("no cache")

    storage.download_file.side_effect = download
    storage.upload_file.side_effect = lambda bucket, key, content, ctype: cached.__setitem__(key, content)
    with patch.object(ps, "_generate_preview", return_value=(b"PDF", "pdf", "application/pdf", False)):
        out = ps.preview_url_for("d1", "report.hwp", "orig/key")

    assert out == ("https://signed/preview/v2/d1.pdf", "pdf", False)
    assert list(cached) == ["preview/v2/d1.pdf"]
    assert ps.preview_is_faithful("d1", "report.hwp") is True


def test_preview_url_html_fallback_result_is_cached_as_html(storage):
    storage.download_file.side_effect = lambda b, k: (
        b"ORIG" if b == settings.minio_bucket_originals else (_ for _ in ()).throw(KeyError(k))
    )

    with patch.object(ps, "_generate_preview",
                      return_value=(b"<p/>", "html", "text/html; charset=utf-8", True)):
        out = ps.preview_url_for("d1", "a.docx", "k")

    assert storage.upload_file.call_args.args[1] == "preview/v2/d1.html"
    assert out == ("https://signed/preview/v2/d1.html", "html", True)
