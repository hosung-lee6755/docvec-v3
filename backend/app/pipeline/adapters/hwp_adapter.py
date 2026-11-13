from pathlib import Path

from app.pipeline.adapters.base import (
    AdapterCapabilities,
    BaseAdapter,
    RawImageRegion,
    RawPage,
    RawParsedDocument,
    RawTableCandidate,
    RawTextBlock,
)

_IMAGE_MAGIC_PREFIXES = (b"\x89PNG", b"\xff\xd8", b"BM", b"GIF8", b"II*\x00", b"MM\x00*")
_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tiff", ".tif")


def _looks_like_image(data: bytes) -> bool:
    return any(data.startswith(magic) for magic in _IMAGE_MAGIC_PREFIXES)


def _hwp_bindata_images(file_path) -> list[bytes]:
    """Reads embedded images from a binary .hwp's BinData/* OLE streams.
    Individual streams may be raw or raw-deflate compressed depending on each
    BinData record's compression flag (not re-parsed here) — detect by image
    magic bytes first, then fall back to zlib raw-window decompression."""
    import zlib

    import olefile

    images: list[bytes] = []
    ole = olefile.OleFileIO(str(file_path))
    try:
        for entry in ole.listdir():
            if len(entry) != 2 or entry[0] != "BinData":
                continue
            if not entry[1].lower().endswith(_IMAGE_SUFFIXES):
                continue
            data = ole.openstream(entry).read()
            if not _looks_like_image(data):
                try:
                    data = zlib.decompress(data, -15)
                except Exception:
                    continue
                if not _looks_like_image(data):
                    continue
            images.append(data)
    finally:
        ole.close()
    return images


def _hwpx_bindata_images(zf) -> list[bytes]:
    return [
        zf.read(name)
        for name in sorted(zf.namelist())
        if "BinData/" in name and name.lower().endswith(_IMAGE_SUFFIXES)
    ]


def _hwpx_local_tag(elem) -> str:
    tag = elem.tag
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _hwpx_collect_text(elem, *, skip_tables: bool = False) -> str:
    if not skip_tables:
        return "".join(t.text or "" for t in elem.iter() if _hwpx_local_tag(t) == "t")

    parts: list[str] = []

    def _walk(e) -> None:
        tag = _hwpx_local_tag(e)
        if tag == "t":
            parts.append(e.text or "")
            return
        if tag == "tbl":
            return
        for child in e:
            _walk(child)

    _walk(elem)
    return "".join(parts)


# 셀 안의 여러 문단을 잇는 구분자. 예전에는 글자를 그대로 붙여 "사업계획서- 국세…"처럼 항목이 붙었다
# (2026-11-13 검토). 표 텍스트는 " | "로 셀을 나누므로 그와 겹치지 않는 구분자를 쓴다
CELL_PARAGRAPH_SEP = " / "


def _record(order: list | None, kind: str, index: int) -> None:
    """문단("p")과 표("t")가 문서에 나온 순서를 남긴다. 추출할 때 이 순서로 블록을 만든다."""
    if order is not None:
        order.append((kind, index))


def _hwpx_cell_text(tc) -> str:
    parts: list[str] = []

    def _walk(e) -> None:
        for child in e:
            if _hwpx_local_tag(child) == "p":
                text = _hwpx_collect_text(child).strip()
                if text:
                    parts.append(text)
            else:
                _walk(child)

    _walk(tc)
    return CELL_PARAGRAPH_SEP.join(parts)


def _hwpx_table_rows(tbl_elem) -> list[list[str]]:
    rows = []
    for tr in tbl_elem:
        if _hwpx_local_tag(tr) != "tr":
            continue
        cells = [_hwpx_cell_text(tc) for tc in tr if _hwpx_local_tag(tc) == "tc"]
        if any(cells):
            rows.append(cells)
    return rows


def _collect_nested_hwpx_tables(elem, tables: list[list[list[str]]], order: list | None = None) -> None:
    """HWPX anchors a table as an inline object inside its host paragraph's
    run (hp:p > hp:run > hp:tbl), not as the paragraph's sibling — so once a
    paragraph's own text is collected, its children must still be searched
    for a nested hp:tbl. Only looks for hp:tbl, never re-descends into hp:p,
    so this can't create duplicate top-level paragraph entries."""
    for child in elem:
        if _hwpx_local_tag(child) == "tbl":
            rows = _hwpx_table_rows(child)
            if rows:
                tables.append(rows)
                _record(order, "t", len(tables) - 1)
            continue
        _collect_nested_hwpx_tables(child, tables, order)


def _hwp_collect_text(elem) -> str:
    """Concatenates this element's own Text runs, skipping over any nested
    TableControl/GShapeObjectControl subtree so an anchored table's or
    image's content isn't folded into the anchoring paragraph's text."""
    texts = []
    for child in elem:
        tag = child.tag
        if tag == "Text":
            texts.append(child.text or "")
        elif tag in ("TableControl", "GShapeObjectControl"):
            continue
        else:
            texts.append(_hwp_collect_text(child))
    return "".join(texts)


def _hwp_table_rows(table_body_elem) -> list[list[str]]:
    rows = []
    for row in table_body_elem:
        if row.tag != "TableRow":
            continue
        cells = []
        for cell in row:
            if cell.tag != "TableCell":
                continue
            parts = [
                _hwp_collect_text(p).strip()
                for p in cell
                if p.tag == "Paragraph" and _hwp_collect_text(p).strip()
            ]
            cells.append(CELL_PARAGRAPH_SEP.join(parts))
        if any(cells):
            rows.append(cells)
    return rows


def _walk_hwp_body(
    elem, paragraphs: list[str], tables: list[list[list[str]]], order: list | None = None,
) -> None:
    """Walks pyhwp's nested XML model of a binary .hwp document. A table is
    anchored inline inside its host paragraph's LineSeg (Paragraph > LineSeg >
    TableControl), so unlike _walk_hwpx, a Paragraph must still descend into
    its children after collecting its own text to discover any anchored
    table — _hwp_collect_text already excludes TableControl subtrees from
    that text so the table's cell content isn't double-counted."""
    tag = elem.tag
    if tag == "TableControl":
        table_body = None
        caption = None
        for child in elem:
            if child.tag == "TableBody":
                table_body = child
            elif child.tag == "TableCaption":
                caption = child
        if caption is not None:
            _walk_hwp_body(caption, paragraphs, tables, order)
        if table_body is not None:
            rows = _hwp_table_rows(table_body)
            if rows:
                tables.append(rows)
                _record(order, "t", len(tables) - 1)
        return
    if tag == "GShapeObjectControl":
        return
    if tag == "Paragraph":
        text = _hwp_collect_text(elem).strip()
        if text:
            paragraphs.append(text)
            _record(order, "p", len(paragraphs) - 1)
        for child in elem:
            _walk_hwp_body(child, paragraphs, tables, order)
        return
    for child in elem:
        _walk_hwp_body(child, paragraphs, tables, order)


def _walk_hwpx(
    elem, paragraphs: list[str], tables: list[list[list[str]]], order: list | None = None,
) -> None:
    """Walks an HWPX section XML tree, separating table cells from loose
    paragraph text. A table is anchored inline inside its host paragraph's
    run (hp:p > hp:run > hp:tbl), so a paragraph must still descend into its
    children after collecting its own text to discover any anchored table —
    _hwpx_collect_text(skip_tables=True) already excludes hp:tbl subtrees
    from that text so the table's cell content isn't double-counted."""
    tag = _hwpx_local_tag(elem)
    if tag == "tbl":
        rows = _hwpx_table_rows(elem)
        if rows:
            tables.append(rows)
            _record(order, "t", len(tables) - 1)
        return
    if tag == "p":
        text = _hwpx_collect_text(elem, skip_tables=True).strip()
        if text:
            paragraphs.append(text)
            _record(order, "p", len(paragraphs) - 1)
        _collect_nested_hwpx_tables(elem, tables, order)
        return
    for child in elem:
        _walk_hwpx(child, paragraphs, tables, order)


def _ordered_text_blocks(
    paragraphs: list[str], tables: list[list[list[str]]], order: list[tuple[str, int]],
) -> tuple[list[RawTextBlock], list[RawTableCandidate]]:
    """문단과 표를 문서에 나온 순서대로 블록으로 만든다. 예전에는 표를 모두 문서 끝에 붙여 표가 설명 문단과
    떨어지고, 청크에서 무슨 표인지 알 수 없었다(2026-11-13 검토). 표 번호 [표 N]도 문서 순서다."""
    table_candidates = [RawTableCandidate(page_number=1, rows=rows) for rows in tables]
    text_blocks: list[RawTextBlock] = []
    for kind, index in order:
        if kind == "p":
            text_blocks.append(RawTextBlock(text=paragraphs[index], page_number=1))
            continue
        table_text = "\n".join(" | ".join(row) for row in tables[index])
        text_blocks.append(
            RawTextBlock(text=f"[표 {index + 1}]\n{table_text}", page_number=1, block_type="table")
        )
    return text_blocks, table_candidates


class HWPAdapter(BaseAdapter):
    @property
    def format_id(self) -> str:
        return "hwp"

    @property
    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            native_text=True,
            native_table=True,
            native_image=False,
            native_structure=True,
            bbox_available=False,
            reading_order=True,
            ocr_required=False,
        )

    def can_handle(self, file_path: Path, mime_type: str) -> bool:
        suffix = file_path.suffix.lower()
        return suffix in {".hwp", ".hwpx"} or mime_type in {
            "application/x-hwp",
            "application/haansofthwp",
        }

    def extract(self, file_path: Path, options: dict) -> RawParsedDocument:
        # Deliberately does not populate metadata["line_layout"] (문서 파싱
        # 고도화 Phase 1) — pyhwp exposes no stable per-run font-size/bold API
        # for HWP/HWPX, unlike pdfplumber's page.chars or python-docx's
        # run.font. structure_blocks.py falls back to its regex-only path for
        # any document with no line_layout, so this is a silent, safe no-op
        # rather than a half-populated/misleading signal.
        suffix = file_path.suffix.lower()
        if suffix == ".hwpx":
            return self._extract_hwpx(file_path)
        return self._extract_hwp(file_path)

    def _extract_hwp(self, file_path: Path) -> RawParsedDocument:
        try:
            from io import BytesIO

            from hwp5.xmlmodel import Hwp5File

            from app.core.safe_xml import parse_xml_bytes
        except ImportError:
            return RawParsedDocument(
                format_id="hwp",
                page_count=0,
                pages=[],
                metadata={},
                warnings=["pyhwp library not installed; cannot parse .hwp files"],
            )

        paragraphs: list[str] = []
        raw_tables: list[list[list[str]]] = []
        order: list[tuple[str, int]] = []
        try:
            buf = BytesIO()
            Hwp5File(str(file_path)).xmlevents(embedbin=False).dump(buf, xml_declaration=True)
            root = parse_xml_bytes(buf.getvalue())
            body = root.find("BodyText")
            if body is not None:
                _walk_hwp_body(body, paragraphs, raw_tables, order)
        except Exception as exc:
            return RawParsedDocument(
                format_id="hwp",
                page_count=0,
                pages=[],
                metadata={},
                warnings=[f"HWP extraction failed: {exc}"],
            )

        # One block per paragraph (not one joined block for the whole document)
        # so a later repagination pass (see process.py::_repaginate_hwp_like)
        # can match each paragraph against the rendered preview PDF's per-page
        # text and assign it a real page number — see hwp_adapter.py's
        # page_number=1 placeholders below, which that pass overwrites.
        text_blocks, table_candidates = _ordered_text_blocks(paragraphs, raw_tables, order)

        warnings: list[str] = []
        image_regions: list[RawImageRegion] = []
        try:
            image_regions = [
                RawImageRegion(page_number=1, bbox=(0, 0, 0, 0), image_bytes=data)
                for data in _hwp_bindata_images(file_path)
            ]
        except Exception as img_exc:
            warnings.append(f"HWP image extraction failed: {img_exc}")

        page = RawPage(
            page_number=1,
            width=595,
            height=842,
            text_blocks=text_blocks,
            table_candidates=table_candidates,
            image_regions=image_regions,
        )
        return RawParsedDocument(
            format_id="hwp", page_count=1, pages=[page], metadata={}, warnings=warnings
        )

    def _extract_hwpx(self, file_path: Path) -> RawParsedDocument:
        import zipfile

        from app.core.safe_xml import parse_xml

        paragraphs: list[str] = []
        raw_tables: list[list[list[str]]] = []
        order: list[tuple[str, int]] = []
        try:
            with zipfile.ZipFile(file_path, "r") as z:
                for name in sorted(z.namelist()):
                    if name.startswith("Contents/") and name.endswith(".xml"):
                        with z.open(name) as f:
                            _walk_hwpx(parse_xml(f), paragraphs, raw_tables, order)
                raw_images = _hwpx_bindata_images(z)
        except Exception as exc:
            return RawParsedDocument(
                format_id="hwpx",
                page_count=0,
                pages=[],
                metadata={},
                warnings=[f"HWPX extraction failed: {exc}"],
            )

        # See the matching comment in _extract_hwp: one block per paragraph so
        # the repagination pass can locate each paragraph independently in the
        # rendered preview PDF's per-page text.
        text_blocks, table_candidates = _ordered_text_blocks(paragraphs, raw_tables, order)

        page = RawPage(
            page_number=1,
            width=595,
            height=842,
            text_blocks=text_blocks,
            table_candidates=table_candidates,
            image_regions=[
                RawImageRegion(page_number=1, bbox=(0, 0, 0, 0), image_bytes=data)
                for data in raw_images
            ],
        )
        return RawParsedDocument(
            format_id="hwpx", page_count=1, pages=[page], metadata={}, warnings=[]
        )

    def extract_metadata(self, file_path: Path) -> dict:
        return {"file_path": str(file_path)}
