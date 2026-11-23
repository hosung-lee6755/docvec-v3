import re
from pathlib import Path
from typing import Iterator

from app.pipeline.blocks.table_markdown import rows_to_markdown

from app.pipeline.adapters.base import (
    AdapterCapabilities,
    BaseAdapter,
    RawImageRegion,
    RawPage,
    RawParsedDocument,
    RawTableCandidate,
    RawTextBlock,
)

# Word 의 제목 스타일 이름. 한국어 Word 는 "제목 1"로 저장하기도 한다
_HEADING_STYLE_RE = re.compile(r"^(?:heading|제목)\s*(\d)$", re.IGNORECASE)
_TITLE_STYLE_NAMES = frozenset({"title", "제목"})
# w:outlineLvl 은 0부터 세고, 9는 본문 수준이다
_BODY_OUTLINE_LEVEL = 9


def _outline_level(element) -> int | None:
    """문단이나 스타일의 w:pPr/w:outlineLvl 값을 1부터 세는 제목 수준으로 바꾼다. 없거나 본문 수준이면 None."""
    from docx.oxml.ns import qn

    ppr = element.find(qn("w:pPr")) if element is not None else None
    outline = ppr.find(qn("w:outlineLvl")) if ppr is not None else None
    if outline is None:
        return None
    try:
        value = int(outline.get(qn("w:val")))
    except (TypeError, ValueError):
        return None
    return value + 1 if 0 <= value < _BODY_OUTLINE_LEVEL else None


def _heading_level(paragraph) -> int | None:
    """문서가 스스로 표시한 제목 수준. 문단에 직접 준 개요 수준이 먼저이고, 없으면 스타일과 그 바탕 스타일을
    차례로 본다("Heading N", "Title", 스타일의 개요 수준). HWPX 의 개요 수준처럼 구조 분석의 heading_level 로 넘긴다.
    예전에는 스타일 이름만 넘겨, 글자 크기를 문단에 직접 주지 않은 Word 제목이 본문 문단이 됐다(2026-11-20 감사)."""
    direct = _outline_level(paragraph._p)
    if direct is not None:
        return direct
    style = paragraph.style
    seen = 0
    while style is not None and seen < 10:
        name = (style.name or "").strip()
        if name.lower() in _TITLE_STYLE_NAMES:
            return 1
        match = _HEADING_STYLE_RE.match(name)
        if match:
            return int(match.group(1)) or 1
        level = _outline_level(style.element)
        if level is not None:
            return level
        style = style.base_style
        seen += 1
    return None


_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tiff", ".tif")


def _docx_embedded_images(file_path: Path) -> list[bytes]:
    """A .docx is a zip; embedded media live under word/media/*. Read them
    directly instead of walking python-docx relationship objects — inline
    position isn't recoverable either way (docx has no fixed pages)."""
    import zipfile

    images: list[bytes] = []
    with zipfile.ZipFile(file_path, "r") as z:
        for name in sorted(z.namelist()):
            if name.startswith("word/media/") and name.lower().endswith(_IMAGE_SUFFIXES):
                images.append(z.read(name))
    return images


def _iter_block_items(doc) -> Iterator[object]:
    """Yield each body-level paragraph/table in true document order.

    doc.paragraphs and doc.tables are separate flat lists — a table sitting
    between two paragraphs in the source ends up entirely after both once
    read that way, scrambling reading order for any docx with an inline
    table. Walking doc.element.body directly preserves the actual order."""
    from docx.oxml.ns import qn
    from docx.table import Table as DocxTable
    from docx.text.paragraph import Paragraph as DocxParagraph

    for child in doc.element.body.iterchildren():
        if child.tag == qn("w:p"):
            yield DocxParagraph(child, doc)
        elif child.tag == qn("w:tbl"):
            yield DocxTable(child, doc)


def _word_page_count(file_path: Path) -> int | None:
    """docProps/app.xml 의 <Pages> 값(Word 가 마지막 저장 때 기록). 없거나 읽을 수 없으면 None.

    <Words> 가 0 이거나 없으면 생성기가 심어 둔 템플릿 값(Pages=1, Words=0)이라 실제 쪽수가 아니므로 쓰지 않는다."""
    try:
        import re
        import zipfile

        with zipfile.ZipFile(file_path) as archive:
            app_xml = archive.read("docProps/app.xml").decode("utf-8", "ignore")
        pages = re.search(r"<Pages>\s*(\d+)\s*</Pages>", app_xml)
        words = re.search(r"<Words>\s*(\d+)\s*</Words>", app_xml)
        if not pages or not words or int(words.group(1)) <= 0:
            return None
        return int(pages.group(1))
    except Exception:
        return None


class DOCXAdapter(BaseAdapter):
    @property
    def format_id(self) -> str:
        return "docx"

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
        return (
            file_path.suffix.lower() == ".docx"
            or mime_type
            == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )

    def extract(self, file_path: Path, options: dict) -> RawParsedDocument:
        try:
            from docx import Document as DocxDocument  # type: ignore[import]
        except ImportError:
            return RawParsedDocument(
                format_id="docx",
                page_count=0,
                pages=[],
                metadata={},
                warnings=["python-docx library not installed; cannot parse .docx files"],
            )

        try:
            from docx.table import Table as DocxTable
            from docx.text.paragraph import Paragraph as DocxParagraph

            doc = DocxDocument(str(file_path))
            extract_font_signals = options.get("extract_font_signals", True)

            text_blocks: list[RawTextBlock] = []
            table_candidates: list[RawTableCandidate] = []
            # Per-paragraph font signals for font-aware structure analysis
            # (문서 파싱 고도화 Phase 1/2) — a side artifact alongside full_text,
            # not a replacement for it (see base.py's RawTextBlock comment).
            # Skippable via options["extract_font_signals"] (문서 파싱 고도화
            # Phase 3 config toggle, TextExtractConfig.extract_font_signals) —
            # default True matches pre-toggle behavior.
            line_layout: list[dict] = []
            table_ordinal = 0

            for item in _iter_block_items(doc):
                if isinstance(item, DocxParagraph):
                    stripped = item.text.strip()
                    if not stripped:
                        continue
                    text_blocks.append(RawTextBlock(text=stripped, page_number=1))
                    if extract_font_signals:
                        sizes = [r.font.size.pt for r in item.runs if r.font.size]
                        font_size = max(set(sizes), key=sizes.count) if sizes else None
                        # 메타 정보 생성.txt 2절 font_name — run.font.name(직접
                        # 지정된 글꼴)이 비어 있으면 문단 style의 글꼴을 폴백으로
                        # 쓴다(item.style.font.name, 대부분의 본문 텍스트는 직접
                        # run.font.name을 지정하지 않고 스타일의 글꼴을 상속받음).
                        names = [r.font.name for r in item.runs if r.font.name] or (
                            [item.style.font.name] if item.style and item.style.font.name else []
                        )
                        font_name = max(set(names), key=names.count) if names else None
                        line_layout.append({
                            "page_number": 1,
                            "text": stripped,
                            "bbox": None,
                            "font_size": font_size,
                            "is_bold": any(r.font.bold for r in item.runs if r.font.bold is True),
                            "is_italic": any(r.font.italic for r in item.runs if r.font.italic is True),
                            "style_name": item.style.name if item.style else None,
                            "font_name": font_name,
                            "heading_level": _heading_level(item),
                        })
                elif isinstance(item, DocxTable):
                    rows = [[cell.text.strip() for cell in row.cells] for row in item.rows]
                    cleaned_rows = [row for row in rows if any(cell for cell in row)]
                    if not cleaned_rows:
                        continue
                    table_ordinal += 1
                    table_candidates.append(RawTableCandidate(page_number=1, rows=cleaned_rows))
                    table_text = rows_to_markdown(cleaned_rows)
                    text_blocks.append(
                        RawTextBlock(
                            text=f"[표 {table_ordinal}]\n{table_text}",
                            page_number=1,
                            block_type="table",
                        )
                    )

            warnings: list[str] = []
            image_regions: list[RawImageRegion] = []
            try:
                image_regions = [
                    RawImageRegion(page_number=1, bbox=(0, 0, 0, 0), image_bytes=data)
                    for data in _docx_embedded_images(file_path)
                ]
            except Exception as img_exc:
                warnings.append(f"DOCX image extraction failed: {img_exc}")

            page = RawPage(
                page_number=1,
                width=595,
                height=842,
                text_blocks=text_blocks,
                table_candidates=table_candidates,
                image_regions=image_regions,
            )
            # 메타 정보 생성.txt 1절 document_created_at — docx core properties에
            # 이미 있는 값을 읽기만 하면 되므로(신규 의존성 없음) 문서 자체의
            # 작성일로 그대로 사용한다. 손상된 파일 등으로 못 읽으면 None.
            document_created_at = None
            try:
                document_created_at = doc.core_properties.created
            except Exception:
                pass

            document_title = None
            try:
                document_title = (doc.core_properties.title or "").strip() or None
            except Exception:
                pass

            return RawParsedDocument(
                format_id="docx",
                page_count=1,
                pages=[page],
                metadata={
                    "line_layout": line_layout, "document_created_at": document_created_at,
                    "document_title": document_title,
                    # Word 가 저장할 때 app.xml 에 남기는 쪽수 — 미리보기 PDF 를 못 만들 때의 대체값.
                    "document_pages": _word_page_count(file_path),
                },
                warnings=warnings,
            )
        except Exception as exc:
            return RawParsedDocument(
                format_id="docx",
                page_count=0,
                pages=[],
                metadata={},
                warnings=[f"DOCX extraction failed: {exc}"],
            )

    def extract_metadata(self, file_path: Path) -> dict:
        return {"file_path": str(file_path)}
