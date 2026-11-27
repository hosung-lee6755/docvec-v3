"""Real-PDF previews for formats the browser can't render natively.

PDF is displayed directly via the browser's built-in viewer. DOCX, PPTX and XLSX
convert to PDF natively via LibreOffice headless. HWP/HWPX convert the same way
through the H2Orestart LibreOffice extension, which opens the original file
directly (2026-11-23). Uploaded HTML is rendered from the original file after
scripts and external references are stripped (preview_html). When the original
can't be opened (the extension is missing, a broken file), HWP/HWPX fall back to
a PDF rebuilt from our own paragraph/table extraction, and that result is marked
approximate. Results are cached in the artifacts bucket as
preview/v2/{document_id}.pdf or .html and served via presigned URL so an
<iframe> can load them without an Authorization header.
"""

import contextlib
import io
import logging
import os
import signal
import subprocess
import tempfile
from pathlib import Path

from app.core.config import settings
from app.pipeline.formats import IMAGE_SUFFIXES
from app.services.storage import storage_service

logger = logging.getLogger(__name__)

# 한글 원본을 H2Orestart로 열면 그림이 많은 문서는 오래 걸린다(NS-AM 검사 매뉴얼 19쪽에 119초, 2026-11-23)
_SOFFICE_TIMEOUT_SECONDS = 300

# 한글 글꼴을 먼저 둔다. sans-serif 만 두면 LibreOffice가 따옴표와 영문을 DejaVu Sans 로, 한글을 나눔고딕으로 나눠
# 그려 PDF 글 순서가 바뀌었다("(‘국내조선업생산액’)"이 "(‘’국내조선업생산액)"으로 뽑혀 쪽 맞춤이 어긋났다, 2026-11-25)
_HTML_WRAP = (
    '<!doctype html><html><head><meta charset="utf-8">'
    "<style>body{{font-family:'NanumGothic','Malgun Gothic',sans-serif;line-height:1.6;padding:16px;max-width:900px;margin:0 auto}}"
    "table{{border-collapse:collapse;margin:8px 0}}td,th{{border:1px solid #cbd5e1;padding:4px 8px;font-size:13px}}"
    "img{{max-width:100%}}</style></head><body>{body}</body></html>"
)


def _docx_to_html(raw: bytes) -> str:
    import mammoth

    result = mammoth.convert_to_html(io.BytesIO(raw))
    return _HTML_WRAP.format(body=result.value)


def _grid_to_html(rows: list[list[str]], spans: list[dict]) -> str:
    """격자를 표로 그린다. 합친 칸은 rowspan/colspan 으로 한 번만 쓰고, 그 칸이 덮는 자리는 건너뛴다."""
    import html as html_mod

    from app.pipeline.adapters.hwp_adapter import CELL_PARAGRAPH_SEP

    origin = {(s["row"], s["col"]): s for s in spans}
    covered = {
        (s["row"] + dr, s["col"] + dc)
        for s in spans
        for dr in range(s["row_span"])
        for dc in range(s["col_span"])
        if dr or dc
    }
    rows_html = []
    for r, row in enumerate(rows):
        cells = []
        for c, text in enumerate(row):
            if (r, c) in covered:
                continue
            span = origin.get((r, c))
            attrs = ""
            if span is not None:
                attrs += f' rowspan="{span["row_span"]}"' if span["row_span"] > 1 else ""
                attrs += f' colspan="{span["col_span"]}"' if span["col_span"] > 1 else ""
            # 칸 안 문단 구분자(" / ")는 추출 글에만 쓰는 표시라 줄바꿈으로 그린다
            body = "<br>".join(html_mod.escape(part) for part in text.split(CELL_PARAGRAPH_SEP))
            cells.append(f"<td{attrs}>{body}</td>")
        rows_html.append(f"<tr>{''.join(cells)}</tr>")
    return f"<table>{''.join(rows_html)}</table>"


def _hwp_to_html(raw: bytes) -> str:
    """구형 HWP를 문단과 표 순서대로 다시 그린다. 본문 추출(hwp_adapter)과 같은 pyhwp XML 모델을 읽는다.

    예전에는 pyhwp의 hwp5html XSLT를 썼다. H2Orestart가 열지 못한 HWP(scandif 항만수요예측 보고서들)에서
    이 변환이 10~17분 걸렸고, 추출 일꾼이 하나라 뒤 문서들이 그동안 '검증중'에 머물렀다(2026-11-25).
    같은 파일을 XML로 읽는 데는 몇 초면 된다. 배치와 글꼴은 단순해지지만 원본과 다를 수 있다는 안내가 붙는
    재구성 미리보기이고, 쪽 맞춤은 추출 블록과 글이 같아 오히려 잘 맞는다."""
    import html as html_mod

    from hwp5.xmlmodel import Hwp5File

    from app.core.safe_xml import parse_xml_bytes
    from app.pipeline.adapters.hwp5_structure import hwp_table_grid
    from app.pipeline.adapters.hwp_adapter import _hwp_cell_text, _hwp_collect_text

    with tempfile.NamedTemporaryFile(suffix=".hwp", delete=False) as tmp:
        tmp.write(raw)
        tmp_path = Path(tmp.name)
    try:
        buf = io.BytesIO()
        Hwp5File(str(tmp_path)).xmlevents(embedbin=False).dump(buf, xml_declaration=True)
    finally:
        tmp_path.unlink(missing_ok=True)

    parts: list[str] = []

    def walk(elem) -> None:
        tag = elem.tag
        if tag == "TableControl":
            for child in elem:
                if child.tag == "TableCaption":
                    walk(child)
            for child in elem:
                if child.tag == "TableBody":
                    rows, spans = hwp_table_grid(child, _hwp_cell_text)
                    if rows:
                        parts.append(_grid_to_html(rows, spans))
            return
        if tag == "GShapeObjectControl":
            return
        if tag == "Paragraph":
            text = _hwp_collect_text(elem).strip()
            if text:
                parts.append(f"<p>{html_mod.escape(text)}</p>")
        for child in elem:
            walk(child)

    root = parse_xml_bytes(buf.getvalue())
    body = root.find("BodyText")
    if body is not None:
        walk(body)
    return _HTML_WRAP.format(body="".join(parts))


def _hwpx_to_html(raw: bytes) -> str:
    """Document-order render of HWPX paragraphs/tables — layout is simplified,
    but reading order and table structure match the original."""
    import html as html_mod
    import zipfile

    from app.core.safe_xml import parse_xml
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
                    walk(parse_xml(f))

    return _HTML_WRAP.format(body="".join(parts))


class SofficeTimeoutError(RuntimeError):
    """LibreOffice 변환이 _SOFFICE_TIMEOUT_SECONDS 안에 끝나지 않았다."""


def _soffice_convert(input_path: Path, target: str, export_filter: str = "") -> Path:
    """Runs `soffice --headless --convert-to <target>` next to the input file, in
    an isolated profile dir (required so concurrent conversions don't collide over
    the LibreOffice user profile lock), and returns the output path. export_filter
    는 "calc_pdf_Export:{...}" 처럼 내보내기 필터와 옵션을 붙일 때 쓴다."""
    work = input_path.parent
    output_path = work / f"{input_path.stem}.{target}"
    returncode, stderr_bytes = _run_soffice(
        [
            "soffice",
            "--headless",
            "--norestore",
            "--nolockcheck",
            f"-env:UserInstallation=file://{work / 'profile'}",
            "--convert-to",
            f"{target}:{export_filter}" if export_filter else target,
            "--outdir",
            str(work),
            str(input_path),
        ],
        _SOFFICE_TIMEOUT_SECONDS,
    )
    if output_path.exists() and (returncode == 0 or _is_complete_output(output_path, target)):
        if returncode != 0:
            # H2Orestart(Java)를 쓴 변환은 결과를 다 쓴 뒤 끝내는 중에 비정상 종료(rc=134)할 때가 있다(2026-11-23)
            logger.warning("LibreOffice exited with %d after writing a complete %s; using it", returncode, target)
        return output_path
    stderr = stderr_bytes.decode("utf-8", errors="replace")
    raise RuntimeError(f"LibreOffice conversion failed: {stderr[:500]}")


def _is_complete_output(path: Path, target: str) -> bool:
    """비정상 종료한 변환이 남긴 파일이 끝까지 쓰였는지. PDF는 머리와 끝 표시, ODT는 압축이 온전하고 본문·스타일이 있다."""
    import zipfile

    data = path.read_bytes()
    if target == "pdf":
        return data.startswith(b"%PDF-") and b"%%EOF" in data[-2048:]
    if target == "odt":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as odt:
                names = set(odt.namelist())
                return odt.testzip() is None and {"content.xml", "styles.xml"} <= names
        except zipfile.BadZipFile:
            return False
    return False


def _soffice_to_pdf(raw: bytes, suffix: str, export_filter: str = "") -> bytes:
    """Converts the raw file to PDF with LibreOffice and returns the PDF bytes."""
    with tempfile.TemporaryDirectory() as workdir:
        input_path = Path(workdir) / f"input{suffix}"
        input_path.write_bytes(raw)
        return _soffice_convert(input_path, "pdf", export_filter).read_bytes()


# 엑셀은 시트 하나를 한 쪽으로 그린다. 인쇄 쪽 나눔으로 그리면 넓은 시트의 열이 여러 쪽으로 잘려 쪽 순서가 행 순서와
# 달랐고, 원문 대조의 쪽과 파싱 본문(시트마다 표)이 맞지 않았다(테이블 정의서 3시트가 14쪽, 2026-11-26).
# 시트에는 원래 쪽이 없으므로 시트 단위가 원본에 더 가깝다
_XLSX_PDF_FILTER = 'calc_pdf_Export:{"SinglePageSheets":{"type":"boolean","value":"true"}}'


def _hwp_original_to_pdf(raw: bytes, suffix: str) -> bytes:
    """HWP·HWPX 원본을 H2Orestart로 ODT로 연 뒤 한글과 쪽 나눔이 달라지는 곳을 고치고 PDF로 그린다(2026-11-23).
    빈 꼬리말이 본문 높이를 줄이고 표 뒤 빈 줄이 다음 쪽으로 밀려, NS-AM 검사 매뉴얼(원본 19쪽)이 34쪽에 빈 쪽까지
    생겼다(preview_odt_fix.py). ODT 단계가 실패하면(일부 HWPX는 ODT로 쓴 뒤 LibreOffice가 비정상 종료한다) 고치지
    않고 원본을 바로 PDF로 그린다."""
    from app.services.preview_odt_fix import fix_hwp_odt

    with tempfile.TemporaryDirectory() as workdir:
        input_path = Path(workdir) / f"input{suffix}"
        input_path.write_bytes(raw)
        try:
            fixed, report = fix_hwp_odt(_soffice_convert(input_path, "odt").read_bytes())
        except SofficeTimeoutError:
            # 원본을 여는 데 시간을 다 썼으면 바로 PDF로 다시 그려도 같은 시간이 걸린다. 재구성 미리보기로 넘긴다
            raise
        except Exception:
            logger.warning("HWP layout fix skipped for %s; converting the original directly", suffix, exc_info=True)
            return _soffice_convert(input_path, "pdf").read_bytes()
        logger.info(
            "HWP layout fix: removed %d empty headers/footers, shrank %d table tails",
            report.removed_headers_footers,
            report.shrunk_table_tails,
        )
        fixed_path = Path(workdir) / "fixed.odt"
        fixed_path.write_bytes(fixed)
        return _soffice_convert(fixed_path, "pdf").read_bytes()


def _run_soffice(cmd: list[str], timeout: int) -> tuple[int, bytes]:
    """soffice를 새 프로세스 그룹으로 띄우고, 시간을 넘기면 그룹 전체를 끝낸다. `soffice`는 셸 스크립트라 실제
    변환은 손자 프로세스(soffice.bin)가 한다. subprocess.run의 timeout은 자식만 끝내 soffice.bin이 남았다."""
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    try:
        _stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        raise SofficeTimeoutError(f"LibreOffice conversion timed out after {timeout}s") from None
    return process.returncode, stderr


def _docx_to_pdf(raw: bytes) -> bytes:
    return _soffice_to_pdf(raw, ".docx")


def _hwp_to_pdf(raw: bytes) -> bytes:
    return _soffice_to_pdf(_hwp_to_html(raw).encode("utf-8"), ".html")


def _hwpx_to_pdf(raw: bytes) -> bytes:
    return _soffice_to_pdf(_hwpx_to_html(raw).encode("utf-8"), ".html")


def _image_to_pdf(suffix: str):
    """이미지는 쪽마다 한 장인 PDF로 보여 준다(여러 장짜리 TIFF도 쪽을 넘기며 볼 수 있다)."""
    def convert(raw: bytes) -> bytes:
        from app.pipeline.adapters.image_adapter import image_to_pdf_bytes

        with tempfile.TemporaryDirectory() as workdir:
            path = Path(workdir) / f"input{suffix}"
            path.write_bytes(raw)
            return image_to_pdf_bytes(path)

    return convert


def _text_to_html(raw: bytes) -> str:
    import html as html_mod

    from app.pipeline.adapters.text_adapter import decode_text

    body = f'<pre style="white-space:pre-wrap;font-family:inherit">{html_mod.escape(decode_text(raw))}</pre>'
    return _HTML_WRAP.format(body=body)


def _csv_to_html(raw: bytes) -> str:
    """CSV는 LibreOffice를 거치지 않고 바로 표로 그린다. 처리 단계와 같은 규칙(parse_csv_rows)으로 읽는다."""
    import html as html_mod

    from app.pipeline.adapters.sheet_adapter import parse_csv_rows

    rows, truncated = parse_csv_rows(raw)
    width = max((len(row) for row in rows), default=0)
    body_rows = "".join(
        "<tr>" + "".join(f"<td>{html_mod.escape(cell)}</td>" for cell in row + [""] * (width - len(row))) + "</tr>"
        for row in rows
    )
    note = "<p>앞부분만 표시했습니다.</p>" if truncated else ""
    return _HTML_WRAP.format(body=f"<table>{body_rows}</table>{note}")


def _uploaded_html_to_html(raw: bytes) -> str:
    """올린 HTML은 그대로 내보내지 않는다(스크립트가 실행된다). 추출한 글과 표만 다시 적는다."""
    import html as html_mod

    from app.pipeline.adapters.text_adapter import decode_text, parse_html

    blocks, _tables, collector, _title = parse_html(decode_text(raw))
    headings = {entry["text"] for entry in collector.line_layout if entry["style_name"]}
    parts = []
    for block in blocks:
        text = html_mod.escape(block.text)
        if block.block_type == "table":
            parts.append(f'<pre style="white-space:pre-wrap">{text}</pre>')
        elif block.text in headings:
            parts.append(f"<h3>{text}</h3>")
        else:
            parts.append(f'<p style="white-space:pre-wrap">{text}</p>')
    return _HTML_WRAP.format(body="".join(parts))


def _uploaded_html_to_pdf(raw: bytes) -> bytes:
    """올린 HTML 원본을 LibreOffice로 그대로 그린다. 스크립트와 외부 참조는 먼저 지운다(preview_html)."""
    from app.pipeline.adapters.text_adapter import decode_text
    from app.services.preview_html import sanitize_html_for_render

    return _soffice_to_pdf(sanitize_html_for_render(decode_text(raw)).encode("utf-8"), ".html")


# 원본 파일을 그대로 그리는 변환. HWP/HWPX는 LibreOffice 확장 H2Orestart가 원본을 직접 연다(2026-11-23).
# 예전에는 우리가 읽은 문단과 표를 HTML로 다시 적어 그렸으므로 원본 배치와 쪽 나눔이 달랐다
_PDF_CONVERTERS = {
    ".docx": _docx_to_pdf,
    ".hwp": lambda raw: _hwp_original_to_pdf(raw, ".hwp"),
    ".hwpx": lambda raw: _hwp_original_to_pdf(raw, ".hwpx"),
    ".html": _uploaded_html_to_pdf,
    ".htm": _uploaded_html_to_pdf,
    ".xlsx": lambda raw: _soffice_to_pdf(raw, ".xlsx", _XLSX_PDF_FILTER),
    ".pptx": lambda raw: _soffice_to_pdf(raw, ".pptx"),
    **{suffix: _image_to_pdf(suffix) for suffix in sorted(IMAGE_SUFFIXES)},
}

# 원본을 직접 열지 못할 때(확장이 없거나 파일을 못 읽을 때) 쓰는 재구성 PDF. 원본과 다를 수 있다
_RECONSTRUCTED_PDF_CONVERTERS = {
    ".hwp": _hwp_to_pdf,
    ".hwpx": _hwpx_to_pdf,
}

_HTML_CONVERTERS = {
    ".docx": _docx_to_html,
    ".hwp": _hwp_to_html,
    ".hwpx": _hwpx_to_html,
    ".csv": _csv_to_html,
    ".txt": _text_to_html,
    ".md": _text_to_html,
    ".html": _uploaded_html_to_html,
    ".htm": _uploaded_html_to_html,
}

# 원본을 그대로 옮긴 미리보기(원본과 다를 수 있다는 안내를 붙이지 않는다). PDF는 _PDF_CONVERTERS 로 만든 것만이다
_FAITHFUL_PDF_SUFFIXES = frozenset({".docx", ".pptx", ".xlsx", ".hwp", ".hwpx", ".html", ".htm"}) | IMAGE_SUFFIXES
_FAITHFUL_HTML_SUFFIXES = frozenset({".csv", ".txt", ".md"})

# 미리보기 캐시. v2 부터 HWP/HWPX/HTML 이 원본에서 그린 PDF다. 예전 재구성본(preview/{id}.pdf)은 다시 쓰지 않는다
PREVIEW_PREFIX = "preview/v2"


def preview_cache_key(document_id: str, ext: str) -> str:
    return f"{PREVIEW_PREFIX}/{document_id}.{ext}"


def _generate_preview(suffix: str, raw: bytes) -> tuple[bytes, str, str, bool]:
    """Returns (content, kind, content_type, approximate). 원본을 그대로 그리는 PDF를 먼저 시도하고, 안 되면
    재구성 PDF, 그다음 HTML 미리보기로 내려간다. approximate 는 원본 배치와 다를 수 있는 결과인지다."""
    from app.pipeline.formats import hwp_suffix_by_content

    suffix = hwp_suffix_by_content(suffix, raw[:8])  # 이름은 .hwp 인데 내용이 HWPX 인 파일(2026-11-27)
    for converters, approximate in ((_PDF_CONVERTERS, False), (_RECONSTRUCTED_PDF_CONVERTERS, True)):
        pdf_converter = converters.get(suffix)
        if pdf_converter is None:
            continue
        try:
            return pdf_converter(raw), "pdf", "application/pdf", approximate
        except Exception:
            logger.exception("PDF preview conversion failed for %s; trying the next converter", suffix)

    html_converter = _HTML_CONVERTERS.get(suffix)
    if html_converter is not None:
        content = html_converter(raw).encode("utf-8")
        return content, "html", "text/html; charset=utf-8", _is_approximate(suffix, "html")

    raise ValueError(f"no preview converter for suffix {suffix}")


def _is_approximate(suffix: str, kind: str) -> bool:
    """형식과 결과 종류만 보고 정하는 기본값. PDF는 원본을 직접 그리는 형식이면 원본 그대로다. 원본을 열지 못해
    재구성 PDF로 내려간 경우는 생성할 때 표시(_APPROXIMATE_MARKER)를 남겨 이 기본값을 덮는다."""
    faithful = _FAITHFUL_PDF_SUFFIXES if kind == "pdf" else _FAITHFUL_HTML_SUFFIXES
    return suffix not in faithful


_APPROXIMATE_MARKER = "approximate"


def _cached(key: str) -> bool:
    try:
        storage_service.download_file(settings.minio_bucket_artifacts, key)
    except Exception:
        return False
    return True


def cached_preview_pdf(document_id: str) -> bytes | None:
    try:
        return storage_service.download_file(settings.minio_bucket_artifacts, preview_cache_key(document_id, "pdf"))
    except Exception:
        return None


def pdf_pages_text_for(document_id: str) -> list[dict] | None:
    """Extracts per-page text directly from the cached preview PDF, when one
    exists. DOCX/HWP/HWPX have no real page boundaries of their own — the
    generated PDF's pagination is the only page structure available, so this
    (not Document.page_map) is what page-syncs the 원문 대조 tab for those
    formats. Returns None if no PDF preview is cached yet."""
    import fitz

    data = cached_preview_pdf(document_id)
    if data is None:
        return None
    doc = fitz.open(stream=data, filetype="pdf")
    try:
        return [{"page_number": i + 1, "text": doc[i].get_text()} for i in range(doc.page_count)]
    finally:
        doc.close()


def preview_is_faithful(document_id: str, filename: str) -> bool:
    """캐시된 미리보기가 원본을 그대로 그린 PDF인지. 원본 재현율을 PDF가 아닌 형식에서도 잴 때 쓴다."""
    suffix = Path(filename).suffix.lower()
    return (
        _cached(preview_cache_key(document_id, "pdf"))
        and not _is_approximate(suffix, "pdf")
        and not _cached(preview_cache_key(document_id, _APPROXIMATE_MARKER))
    )


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

    for kind in ("pdf", "html"):
        cache_key = preview_cache_key(document_id, kind)
        if not _cached(cache_key):
            continue
        url = storage_service.get_presigned_url(settings.minio_bucket_artifacts, cache_key)
        approximate = _is_approximate(suffix, kind) or _cached(preview_cache_key(document_id, _APPROXIMATE_MARKER))
        return url, kind, approximate

    raw = storage_service.download_file(settings.minio_bucket_originals, minio_key)
    content, kind, content_type, approximate = _generate_preview(suffix, raw)
    cache_key = preview_cache_key(document_id, kind)
    storage_service.upload_file(settings.minio_bucket_artifacts, cache_key, content, content_type)
    if approximate and not _is_approximate(suffix, kind):
        storage_service.upload_file(
            settings.minio_bucket_artifacts, preview_cache_key(document_id, _APPROXIMATE_MARKER), b"1", "text/plain"
        )
    url = storage_service.get_presigned_url(settings.minio_bucket_artifacts, cache_key)
    return url, kind, approximate
