from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from uuid import uuid4

from app.pipeline.adapters.base import (
    AdapterCapabilities,
    BaseAdapter,
    RawImageRegion,
    RawPage,
    RawParsedDocument,
    RawTableCandidate,
    RawTextBlock,
)
from app.pipeline.blocks.table_markdown import rows_to_markdown
from app.pipeline.adapters.hwp5_structure import (
    add_hwp_paragraph_marks,
    add_hwp_symbol_chars,
    hwp_paragraph_layout,
    hwp_table_grid,
    load_hwp_styles,
)
from app.pipeline.adapters.hwpx_structure import (
    HwpxStyles,
    add_paragraph_marks,
    add_symbol_chars,
    load_styles,
    paragraph_layout,
    table_grid,
)
from app.pipeline.adapters.hwp_pictures import (
    anchored_image_regions,
    hwp_bin_stems,
    hwp_picture_refs,
    hwpx_manifest_stems,
    hwpx_picture_refs,
)
from app.pipeline.adapters.nested_tables import InnerTables, is_frame_only, is_separable_table

HWPX_HEADER = "Contents/header.xml"
HWPX_MANIFEST = "Contents/content.hpf"

_IMAGE_MAGIC_PREFIXES = (b"\x89PNG", b"\xff\xd8", b"BM", b"GIF8", b"II*\x00", b"MM\x00*")
_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tiff", ".tif")


def _looks_like_image(data: bytes) -> bool:
    return any(data.startswith(magic) for magic in _IMAGE_MAGIC_PREFIXES)


def _hwp_bindata_images(file_path) -> list[bytes]:
    return [data for _stem, data in _hwp_bindata_named(file_path)]


def _hwp_bindata_named(file_path) -> list[tuple[str, bytes]]:
    """Reads embedded images from a binary .hwp's BinData/* OLE streams, with
    each stream's name stem (BIN0001) so body picture controls can point at it.
    Individual streams may be raw or raw-deflate compressed depending on each
    BinData record's compression flag (not re-parsed here) — detect by image
    magic bytes first, then fall back to zlib raw-window decompression."""
    import zlib

    import olefile

    images: list[tuple[str, bytes]] = []
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
            images.append((entry[1].rsplit(".", 1)[0], data))
    finally:
        ole.close()
    return images


def _hwpx_bindata_images(zf) -> list[bytes]:
    return [data for _stem, data in _hwpx_bindata_named(zf)]


def _hwpx_bindata_named(zf, manifest_stems: dict[str, str] | None = None) -> list[tuple[str, bytes]]:
    """BinData 그림을 (참조 이름, 내용)으로. 참조 이름은 본문 hc:img 의 binaryItemIDRef 와 같은 매니페스트 id 이고,
    매니페스트에 없으면 파일 이름 앞부분(image1)이다."""
    id_by_stem = {stem: item_id for item_id, stem in (manifest_stems or {}).items()}
    named = []
    for name in sorted(zf.namelist()):
        if "BinData/" in name and name.lower().endswith(_IMAGE_SUFFIXES):
            stem = name.rsplit("/", 1)[-1].rsplit(".", 1)[0]
            named.append((id_by_stem.get(stem, stem), zf.read(name)))
    return named


def _hwpx_local_tag(elem) -> str:
    tag = elem.tag
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


# <hp:t> 안에 끼는 글자 요소. 요소 자리에 이 글자를 두고, 요소 뒤의 글(tail)도 이어 읽는다. 강제 줄바꿈은 원문처럼 줄을
# 나눈다(예전에는 빈칸으로 적어 화면에서 줄이 이어 붙었다, 2026-11-27). 표 칸 안 줄바꿈은 표를 만들 때 빈칸이 된다
_HWPX_INLINE_CHARS = {"lineBreak": "\n", "tab": " ", "fwSpace": " ", "nbSpace": " ", "hyphen": "-"}


def _hwpx_t_text(t) -> str:
    """<hp:t> 한 개의 글. 줄바꿈, 탭, 전각 공백 같은 요소 뒤의 글은 XML에서 그 요소의 tail 이라 t.text 에 없다.
    예전에는 t.text 만 읽어 "중소벤처기업부<fwSpace/>장관"의 "장관"처럼 요소 뒤 글이 통째로 빠졌다(2026-11-23)."""
    parts = [t.text or ""]
    for child in t:
        parts.append(_HWPX_INLINE_CHARS.get(_hwpx_local_tag(child), ""))
        parts.append("".join(child.itertext()))
        parts.append(child.tail or "")
    return "".join(parts)


# 글에 넣는 자동 번호 종류. 표·그림·수식 제목의 번호("표 7")는 본문 글이지만 쪽 번호·각주 번호 같은 다른 자동 번호는
# 머리말이나 각주 표시라 넣지 않는다. 예전에는 자동 번호를 모두 건너뛰어 "표  컨테이너 …"처럼 번호가 빠졌다(2026-11-25)
_CAPTION_NUMBER_KINDS = frozenset({"table", "picture", "equation"})


def _hwpx_auto_number(elem) -> str:
    """HWPX <hp:autoNum num="4" numType="TABLE"/> 의 번호. 제목 번호가 아니면 빈 글이다."""
    return elem.get("num", "") if (elem.get("numType") or "").lower() in _CAPTION_NUMBER_KINDS else ""


def _hwpx_collect_text(elem, *, skip_tables: bool = False) -> str:
    parts: list[str] = []

    def _walk(e) -> None:
        tag = _hwpx_local_tag(e)
        if tag == "t":
            parts.append(_hwpx_t_text(e))
            return
        if tag == "autoNum":
            parts.append(_hwpx_auto_number(e))
            return
        if tag == "tbl" and skip_tables:
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


def _hwpx_cell_text(tc, inner: InnerTables | None = None) -> str:
    """칸 안 문단 글을 " / "로 잇는다. inner 가 있으면 2행 2열 이상인 안쪽 표는 inner 로 떼어 내고 표시만 남긴다.
    inner 가 없으면(미리보기) 안쪽 표의 글도 칸 글로 이어 받는다."""
    parts: list[str] = []
    _hwpx_cell_parts(tc, parts, inner)
    return CELL_PARAGRAPH_SEP.join(parts)


def _hwpx_cell_parts(elem, parts: list[str], inner: InnerTables | None) -> None:
    for child in elem:
        tag = _hwpx_local_tag(child)
        if tag == "p":
            text = _hwpx_collect_text(child, skip_tables=True).strip()
            if text:
                parts.append(text)
            _hwpx_paragraph_tables(child, parts, inner)
        elif tag == "tbl":
            _hwpx_inner_table(child, parts, inner)
        else:
            _hwpx_cell_parts(child, parts, inner)


def _hwpx_paragraph_tables(elem, parts: list[str], inner: InnerTables | None) -> None:
    """문단에 박힌 표만 찾는다. 문단 글(글상자 안 글 포함)은 _hwpx_collect_text 가 이미 읽었다."""
    for child in elem:
        if _hwpx_local_tag(child) == "tbl":
            _hwpx_inner_table(child, parts, inner)
        else:
            _hwpx_paragraph_tables(child, parts, inner)


def _hwpx_caption(tbl) -> str | None:
    caption = next((child for child in tbl if _hwpx_local_tag(child) == "caption"), None)
    if caption is None:
        return None
    texts = [_hwpx_collect_text(p).strip() for p in caption.iter() if _hwpx_local_tag(p) == "p"]
    return " ".join(text for text in texts if text) or None


def _hwpx_inner_table(tbl, parts: list[str], inner: InnerTables | None) -> None:
    deeper = InnerTables()
    rows, spans = table_grid(tbl, partial(_hwpx_cell_text, inner=deeper))
    if inner is not None and is_separable_table(rows):
        parts.append(inner.add(rows, spans, deeper, _hwpx_caption(tbl)))
        return
    _hwpx_cell_parts(tbl, parts, inner)  # 한 줄짜리 글상자 같은 작은 표는 칸 글로 둔다


@dataclass
class _HwpxContext:
    """HWPX 한 문서를 훑는 동안 모으는 서식 정보(전체 점검 2-2, 2-12)."""

    styles: HwpxStyles = field(default_factory=HwpxStyles)
    # 문단 조각과 같은 순서의 줄 정보(글자 크기, 굵기, 개요 수준)
    layout: list[dict] = field(default_factory=list)
    # 표 번호(0부터) → 합친 칸 목록
    spans: dict[int, list[dict]] = field(default_factory=dict)
    # 표 번호(0부터) → 표 제목. 칸 안에서 떼어 낸 표가 어느 칸에 있었는지 적는다
    titles: dict[int, str] = field(default_factory=dict)
    # 칸 안에서 떼어 낸 표 번호(0부터) → (바깥 표 번호, 들어 있던 칸). 표 후보의 parent_table_id·parent_cell 이 된다
    parents: dict[int, tuple[int, dict | None]] = field(default_factory=dict)
    # 본문에서 만난 그림이 가리키는 BinData 이름 앞부분(문서 순서). order 의 ("img", 순번)이 이 목록을 가리킨다
    image_refs: list[str] = field(default_factory=list)
    # HWP: bindata-id → BinData 스트림 이름 앞부분(hwp_pictures.hwp_bin_stems)
    bin_stems: dict[str, str] = field(default_factory=dict)


def _record_pictures(refs: list[str], order: list | None, ctx: "_HwpxContext | None") -> None:
    """본문에서 만난 그림을 문단·표와 같은 순서 목록에 남긴다. 그림 글은 이 자리 뒤에 놓인다(hwp_pictures.py)."""
    if ctx is None:
        return
    for ref in refs:
        ctx.image_refs.append(ref)
        _record(order, "img", len(ctx.image_refs) - 1)


def _hwpx_table_rows(tbl_elem) -> list[list[str]]:
    return table_grid(tbl_elem, _hwpx_cell_text)[0]


def _add_table(
    rows: list[list[str]], spans: list[dict], inner: InnerTables, title: str | None,
    tables: list, order: list | None, ctx: "_HwpxContext | None",
    parent: tuple[int, dict | None] | None = None,
) -> None:
    """표를 내고, 그 칸 안에서 떼어 낸 표를 바로 뒤에 낸다. 안쪽 표 안의 표도 같은 방식으로 그 뒤에 낸다.
    칸 하나짜리 틀에 표만 들어 있으면 틀은 내지 않고 안쪽 표를 그 자리에 낸다(틀의 부모를 물려받는다).
    표 번호 [표 N]은 문서 순서(index + 1)라 안쪽 표 제목에 바깥 표 번호를 바로 적는다."""
    if is_frame_only(rows):
        for inner_rows, inner_spans, deeper, caption in inner.found:
            _add_table(inner_rows, inner_spans, deeper, caption, tables, order, ctx, parent)
        return
    tables.append(rows)
    index = len(tables) - 1
    if ctx is not None:
        if spans:
            ctx.spans[index] = spans
        if title:
            ctx.titles[index] = title
        if parent is not None:
            ctx.parents[index] = parent
    _record(order, "t", index)
    for inner_rows, inner_spans, deeper, inner_title, host in inner.titled(rows, outer_title=f"[표 {index + 1}]"):
        _add_table(inner_rows, inner_spans, deeper, inner_title, tables, order, ctx, (index, host))


def _add_hwpx_table(tbl_elem, tables: list, order: list | None, ctx: _HwpxContext | None) -> None:
    inner = InnerTables()
    rows, spans = table_grid(tbl_elem, partial(_hwpx_cell_text, inner=inner))
    if rows:
        _add_table(rows, spans, inner, None, tables, order, ctx)


def _collect_nested_hwpx_tables(
    elem, tables: list[list[list[str]]], order: list | None = None, ctx: _HwpxContext | None = None,
) -> None:
    """HWPX anchors a table as an inline object inside its host paragraph's
    run (hp:p > hp:run > hp:tbl), not as the paragraph's sibling — so once a
    paragraph's own text is collected, its children must still be searched
    for a nested hp:tbl. Only looks for hp:tbl, never re-descends into hp:p,
    so this can't create duplicate top-level paragraph entries."""
    for child in elem:
        if _hwpx_local_tag(child) == "tbl":
            _add_hwpx_table(child, tables, order, ctx)
            continue
        _collect_nested_hwpx_tables(child, tables, order, ctx)


# 구형 HWP 문단 안 글자 제어 문자. HWPX 의 _HWPX_INLINE_CHARS 와 같은 글자로 적는다. 예전에는 제어 문자를 모두
# 버려 "-<고정폭 빈칸>관련 프로세스"가 "-관련 프로세스"로, 강제 줄바꿈 앞뒤 낱말이 붙어서 나왔다(2026-11-26 글머리 대조)
_HWP_INLINE_CHARS = {"LINE_BREAK": "\n", "TAB": " ", "FIXWIDTH_SPACE": " ", "NONBREAK_SPACE": " ", "HYPHEN": "-"}


def _hwp_collect_text(elem) -> str:
    """Concatenates this element's own Text runs, skipping over any nested
    TableControl/GShapeObjectControl subtree so an anchored table's or
    image's content isn't folded into the anchoring paragraph's text."""
    texts = []
    for child in elem:
        tag = child.tag
        if tag == "Text":
            texts.append(child.text or "")
        elif tag == "ControlChar":
            texts.append(_HWP_INLINE_CHARS.get(child.get("name") or "", ""))
        elif tag == "AutoNumbering":
            texts.append(child.get("number", "") if child.get("kind") in _CAPTION_NUMBER_KINDS else "")
        elif tag in ("TableControl", "GShapeObjectControl"):
            continue
        else:
            texts.append(_hwp_collect_text(child))
    return "".join(texts)


def _hwp_cell_paragraphs(elem, out: list[str], inner: InnerTables | None = None) -> None:
    """칸 안의 문단 글을 모은다. 문단이 칸 바로 아래가 아니라 단 설정(ColumnSet) 등에 싸여 있어도 찾는다.

    예전에는 칸 바로 아래 문단만 읽어 목차·요구사항 세부내용 칸이 통째로 비고, 칸 안의 표(누출금지 정보 목록,
    재질 규격표)가 사라졌다(3. 제안요청서·NS-AM 검사매뉴얼, 2026-11-20). 칸 안의 표는 _hwp_inner_table 이
    따로 떼어 내거나(2행 2열 이상) 칸 글로 이어 받는다."""
    for child in elem:
        tag = child.tag
        if tag == "Paragraph":
            text = _hwp_collect_text(child).strip()
            if text:
                out.append(text)
            _hwp_nested_table_paragraphs(child, out, inner)
        elif tag != "GShapeObjectControl":
            _hwp_cell_paragraphs(child, out, inner)


def _hwp_nested_table_paragraphs(elem, out: list[str], inner: InnerTables | None = None) -> None:
    """문단에 박힌 표만 찾는다. 문단의 다른 자식 글은 _hwp_collect_text 가 이미 읽었다."""
    for child in elem:
        tag = child.tag
        if tag == "TableControl":
            _hwp_inner_table(child, out, inner)
        elif tag not in ("Paragraph", "GShapeObjectControl"):
            _hwp_nested_table_paragraphs(child, out, inner)


def _hwp_caption(control) -> str | None:
    caption = next((child for child in control if child.tag == "TableCaption"), None)
    if caption is None:
        return None
    parts: list[str] = []
    _hwp_cell_paragraphs(caption, parts)
    return " ".join(parts) or None


def _hwp_inner_table(control, out: list[str], inner: InnerTables | None) -> None:
    """칸 안의 표. 2행 2열 이상이면 inner 로 떼어 내고 칸 글에는 표시만 남긴다. 작은 표는 칸 글로 이어 받는다."""
    body = next((child for child in control if child.tag == "TableBody"), None)
    deeper = InnerTables()
    rows, spans = hwp_table_grid(body, partial(_hwp_cell_text, inner=deeper)) if body is not None else ([], [])
    if inner is not None and is_separable_table(rows):
        out.append(inner.add(rows, spans, deeper, _hwp_caption(control)))
        return
    _hwp_cell_paragraphs(control, out, inner)


def _hwp_cell_text(cell, inner: InnerTables | None = None) -> str:
    parts: list[str] = []
    _hwp_cell_paragraphs(cell, parts, inner)
    return CELL_PARAGRAPH_SEP.join(parts)


def _hwp_table_rows(table_body_elem) -> list[list[str]]:
    return hwp_table_grid(table_body_elem, _hwp_cell_text)[0]


def _walk_hwp_body(
    elem, paragraphs: list[str], tables: list[list[list[str]]], order: list | None = None,
    ctx: "_HwpxContext | None" = None,
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
            _walk_hwp_body(caption, paragraphs, tables, order, ctx)
        if table_body is not None:
            inner = InnerTables()
            rows, spans = hwp_table_grid(table_body, partial(_hwp_cell_text, inner=inner))
            if rows:
                _add_table(rows, spans, inner, None, tables, order, ctx)
            # 칸 안 그림은 표 바로 뒤에 둔다
            _record_pictures(hwp_picture_refs(table_body, ctx.bin_stems if ctx else {}), order, ctx)
        return
    if tag == "GShapeObjectControl":
        _record_pictures(hwp_picture_refs(elem, ctx.bin_stems if ctx else {}), order, ctx)
        return
    if tag == "Paragraph":
        text = _hwp_collect_text(elem).strip()
        if text:
            paragraphs.append(text)
            if ctx is not None:
                ctx.layout.append(hwp_paragraph_layout(elem, text, ctx.styles))
            _record(order, "p", len(paragraphs) - 1)
        for child in elem:
            _walk_hwp_body(child, paragraphs, tables, order, ctx)
        return
    for child in elem:
        _walk_hwp_body(child, paragraphs, tables, order, ctx)


def _walk_hwpx(
    elem, paragraphs: list[str], tables: list[list[list[str]]], order: list | None = None,
    ctx: _HwpxContext | None = None,
) -> None:
    """Walks an HWPX section XML tree, separating table cells from loose
    paragraph text. A table is anchored inline inside its host paragraph's
    run (hp:p > hp:run > hp:tbl), so a paragraph must still descend into its
    children after collecting its own text to discover any anchored table —
    _hwpx_collect_text(skip_tables=True) already excludes hp:tbl subtrees
    from that text so the table's cell content isn't double-counted."""
    tag = _hwpx_local_tag(elem)
    if tag == "tbl":
        _add_hwpx_table(elem, tables, order, ctx)
        _record_pictures(hwpx_picture_refs(elem), order, ctx)
        return
    if tag == "p":
        text = _hwpx_collect_text(elem, skip_tables=True).strip()
        if text:
            paragraphs.append(text)
            _record(order, "p", len(paragraphs) - 1)
            if ctx is not None:
                ctx.layout.append(paragraph_layout(elem, text, ctx.styles))
        _collect_nested_hwpx_tables(elem, tables, order, ctx)
        # 문단(과 그 안의 표 칸)에 박힌 그림은 문단과 표 뒤에 둔다
        _record_pictures(hwpx_picture_refs(elem), order, ctx)
        return
    for child in elem:
        _walk_hwpx(child, paragraphs, tables, order, ctx)


def _ordered_text_blocks(
    paragraphs: list[str], tables: list[list[list[str]]], order: list[tuple[str, int]],
    spans: dict[int, list[dict]] | None = None, titles: dict[int, str] | None = None,
    parents: dict[int, tuple[int, dict | None]] | None = None,
    image_anchors: list | None = None,
) -> tuple[list[RawTextBlock], list[RawTableCandidate]]:
    """문단과 표를 문서에 나온 순서대로 블록으로 만든다. 예전에는 표를 모두 문서 끝에 붙여 표가 설명 문단과
    떨어지고, 청크에서 무슨 표인지 알 수 없었다(2026-11-13 검토). 표 번호 [표 N]도 문서 순서다.
    칸 안에서 떼어 낸 표는 제목을 표 번호 다음 줄에 적는다. 구조 분석은 "[표 N]"만 있는 줄을 표의 시작으로 본다.
    그림("img")은 블록을 만들지 않고, image_anchors 에 (그림 순번, 바로 앞 블록 또는 "start")를 남긴다."""
    titles = titles or {}
    parents = parents or {}
    ids = [str(uuid4()) for _ in tables]
    table_candidates = [
        RawTableCandidate(
            page_number=1, rows=rows, id=ids[index], spans=(spans or {}).get(index), title=titles.get(index),
            parent_table_id=ids[parents[index][0]] if index in parents else None,
            parent_cell=parents[index][1] if index in parents else None,
        )
        for index, rows in enumerate(tables)
    ]
    text_blocks: list[RawTextBlock] = []
    for kind, index in order:
        if kind == "img":
            if image_anchors is not None:
                image_anchors.append((index, text_blocks[-1] if text_blocks else "start"))
            continue
        if kind == "p":
            text_blocks.append(RawTextBlock(text=paragraphs[index], page_number=1))
            continue
        # PDF·DOCX 처럼 Markdown 표로 적는다. 예전에는 "a | b" 줄이라 원문 대조 화면에서 표가 한 줄로 뭉개졌고,
        # 같은 화면에서 PDF 표만 표 모양으로 나왔다(scandif 점검, 2026-11-25)
        table_text = rows_to_markdown(tables[index])
        head = f"[표 {index + 1}]\n{titles[index]}" if index in titles else f"[표 {index + 1}]"
        text_blocks.append(RawTextBlock(text=f"{head}\n{table_text}", page_number=1, block_type="table"))
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
        # 두 형식 모두 metadata["line_layout"]에 문단별 글자 크기, 굵기, 개요 수준을 채운다. HWPX는 XML에서
        # 직접 읽고(hwpx_structure.py), 구형 HWP는 pyhwp가 만든 XML에서 읽는다(hwp5_structure.py, 2026-11-17).
        from app.pipeline.formats import hwp_suffix_by_content

        try:
            with open(file_path, "rb") as fh:
                head = fh.read(8)
        except OSError:
            head = b""
        if hwp_suffix_by_content(file_path.suffix.lower(), head) == ".hwpx":
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
        ctx = _HwpxContext()
        try:
            buf = BytesIO()
            Hwp5File(str(file_path)).xmlevents(embedbin=False).dump(buf, xml_declaration=True)
            root = parse_xml_bytes(buf.getvalue())
            body = root.find("BodyText")
            if body is not None:
                ctx.styles = load_hwp_styles(root)
                add_hwp_paragraph_marks(root)  # 글머리표 문단 모양의 기호를 문단 글 앞에 넣는다
                add_hwp_symbol_chars(root)  # 기호 글꼴 코드(U+F0xx)를 화면에 보이는 글자로 적는다
                ctx.bin_stems = hwp_bin_stems(root)
                _walk_hwp_body(body, paragraphs, raw_tables, order, ctx)
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
        image_anchors: list = []
        text_blocks, table_candidates = _ordered_text_blocks(
            paragraphs, raw_tables, order, ctx.spans, ctx.titles, ctx.parents, image_anchors,
        )

        warnings: list[str] = []
        image_regions: list[RawImageRegion] = []
        try:
            # 그림은 본문에 박힌 자리(그림이 들어 있던 문단 뒤)와 함께 낸다(hwp_pictures.py, 2026-11-23)
            image_regions = anchored_image_regions(ctx.image_refs, image_anchors, _hwp_bindata_named(file_path))
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
            format_id="hwp", page_count=1, pages=[page], metadata={"line_layout": ctx.layout}, warnings=warnings
        )

    def _extract_hwpx(self, file_path: Path) -> RawParsedDocument:
        import zipfile

        from app.core.safe_xml import parse_xml

        paragraphs: list[str] = []
        raw_tables: list[list[list[str]]] = []
        order: list[tuple[str, int]] = []
        ctx = _HwpxContext()
        try:
            with zipfile.ZipFile(file_path, "r") as z:
                if HWPX_HEADER in z.namelist():
                    with z.open(HWPX_HEADER) as f:
                        ctx.styles = load_styles(parse_xml(f))
                for name in sorted(z.namelist()):
                    if name.startswith("Contents/") and name.endswith(".xml"):
                        with z.open(name) as f:
                            section = parse_xml(f)
                        # 글머리표 문단(문단 모양에만 기호가 있다)의 기호를 글로 넣는다(2026-11-26)
                        add_paragraph_marks(section, ctx.styles)
                        add_symbol_chars(section, ctx.styles)  # 기호 글꼴 코드를 화면에 보이는 글자로 적는다
                        _walk_hwpx(section, paragraphs, raw_tables, order, ctx)
                manifest = z.read(HWPX_MANIFEST) if HWPX_MANIFEST in z.namelist() else b""
                named_images = _hwpx_bindata_named(z, hwpx_manifest_stems(manifest) if manifest else None)
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
        image_anchors: list = []
        text_blocks, table_candidates = _ordered_text_blocks(
            paragraphs, raw_tables, order, ctx.spans, ctx.titles, ctx.parents, image_anchors,
        )

        page = RawPage(
            page_number=1,
            width=595,
            height=842,
            text_blocks=text_blocks,
            table_candidates=table_candidates,
            image_regions=anchored_image_regions(ctx.image_refs, image_anchors, named_images),
        )
        return RawParsedDocument(
            format_id="hwpx", page_count=1, pages=[page], metadata={"line_layout": ctx.layout}, warnings=[]
        )

    def extract_metadata(self, file_path: Path) -> dict:
        return {"file_path": str(file_path)}
