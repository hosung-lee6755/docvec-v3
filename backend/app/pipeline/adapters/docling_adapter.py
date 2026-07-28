"""IBM Docling 기반 PDF 어댑터 — Docling 도입 설계서(2026-07-23) Phase 1.

기존 PDFAdapter를 대체하는 게 아니라 `TextExtractConfig.engine=="docling"`일
때만 PDF에 한해 선택적으로 쓰인다(DOCX/HWP/HWPX는 Docling 미지원이라 항상
기존 어댑터). `BaseAdapter` 계약(`RawParsedDocument`/`RawPage`/`RawTextBlock`/
`RawTableCandidate`)을 그대로 따르므로 `TextExtractBlock.run()`의 parsed_text/
extraction_layout/tables 조립 로직은 수정 없이 그대로 재사용된다 — 추가로
`RawParsedDocument.metadata["elements"]`에 통합 요소 JSON(page/type/bbox/
content.markdown/metadata 형태)만 얹는다.

기본 OCR 엔진(RapidOCR)은 한글을 의미 없는 한자 형태로 오인식하는 것을
격리 트라이얼로 실제 확인했다(2026-07-23) — 반드시 EasyOCR을 한국어로 명시
설정해야 한다. Docling 정식 버전의 `ProvenanceItem`/`DocItemLabel` 속성명은
설치된 버전에 따라 달라질 수 있으므로 아래 헬퍼들은 `getattr` 기반으로
방어적으로 값을 꺼낸다 — 실제 docling 패키지가 설치된 뒤(컨테이너 리빌드
후) 실제 문서로 재검증 필요."""
import io
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

# Docling DocItemLabel 값 -> 우리 쪽 block_type/요소 type 매핑. 매핑에 없는
# 라벨(예: caption, footnote 등 세분화된 것들)은 "paragraph"로 취급 —
# structure_analyze(Phase 2)가 이 값을 보고 세분화를 원하면 그때 추가한다.
_TABLE_LABELS = {"table"}
_HEADING_LABELS = {"title", "section_header", "section-header"}
_HEADER_LABELS = {"page_header", "page-header"}
_FOOTER_LABELS = {"page_footer", "page-footer"}
_PICTURE_LABELS = {"picture", "figure"}
_LIST_ITEM_LABELS = {"list_item", "list-item"}
_CAPTION_LABELS = {"caption"}


def _item_label(item) -> str:
    label = getattr(item, "label", None)
    if label is None:
        return "text"
    return str(getattr(label, "value", label)).lower()


def _item_page_and_bbox(item) -> tuple[int, tuple[float, float, float, float] | None]:
    prov = getattr(item, "prov", None) or []
    if not prov:
        return 1, None
    first = prov[0]
    page_no = getattr(first, "page_no", None) or getattr(first, "page", None) or 1
    bbox_obj = getattr(first, "bbox", None)
    if bbox_obj is None:
        return page_no, None
    try:
        bbox = (
            float(getattr(bbox_obj, "l", 0.0)),
            float(getattr(bbox_obj, "t", 0.0)),
            float(getattr(bbox_obj, "r", 0.0)),
            float(getattr(bbox_obj, "b", 0.0)),
        )
    except (TypeError, ValueError):
        bbox = None
    return page_no, bbox


def _table_rows(table_item) -> list[list[str]]:
    try:
        df = table_item.export_to_dataframe()
    except Exception:
        return []
    rows = [[str(c) for c in df.columns]]
    rows.extend([str(v) for v in row] for row in df.itertuples(index=False))
    return rows


class DoclingAdapter(BaseAdapter):
    @property
    def format_id(self) -> str:
        return "pdf"

    @property
    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            native_text=True,
            native_table=True,
            native_image=True,
            native_structure=True,
            bbox_available=True,
            reading_order=True,
            ocr_required=False,
        )

    def can_handle(self, file_path: Path, mime_type: str) -> bool:
        return mime_type == "application/pdf" or file_path.suffix.lower() == ".pdf"

    def extract(self, file_path: Path, options: dict) -> RawParsedDocument:
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import EasyOcrOptions, PdfPipelineOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption

        pipeline_options = PdfPipelineOptions()
        pipeline_options.do_ocr = True
        # 기본 RapidOCR(중국어 모델)이 한글을 한자로 오인식하는 것을 실제
        # 확인함 — 반드시 EasyOCR + 한국어로 명시 설정.
        pipeline_options.ocr_options = EasyOcrOptions(lang=["ko"])
        # generate_picture_images 기본값은 False라 PictureItem.get_image()가
        # 항상 None을 반환했다 — 아래 picture 분기에서 실제 PNG bytes를 얻으려면
        # 반드시 켜야 한다(그림 탭 표출 버그, 2026-07-25).
        pipeline_options.generate_picture_images = True

        converter = DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)}
        )
        result = converter.convert(str(file_path))
        doc = result.document

        pages_by_no: dict[int, RawPage] = {}
        elements: list[dict] = []
        section_path: list[str] = []
        warnings: list[str] = []
        table_ordinal = 0

        def page_for(page_no: int) -> RawPage:
            if page_no not in pages_by_no:
                size = getattr(doc.pages.get(page_no), "size", None) if hasattr(doc, "pages") else None
                width = float(getattr(size, "width", 0.0) or 0.0)
                height = float(getattr(size, "height", 0.0) or 0.0)
                pages_by_no[page_no] = RawPage(
                    page_number=page_no, width=width, height=height,
                    text_blocks=[], table_candidates=[], image_regions=[],
                )
            return pages_by_no[page_no]

        for item, _level in doc.iterate_items():
            label = _item_label(item)
            page_no, bbox = _item_page_and_bbox(item)
            page = page_for(page_no)

            if label in _TABLE_LABELS:
                table_ordinal += 1
                rows = _table_rows(item)
                table_id = str(uuid4())
                page.table_candidates.append(
                    RawTableCandidate(page_number=page_no, rows=rows, bbox=bbox, id=table_id)
                )
                markdown = rows_to_markdown(rows)
                # 표는 지금까지 parsed_text/full_text에 전혀 나타나지 않아
                # TextExtractBlock이 계산할 element_spans에서도 누락되는
                # 실제 갭이었다(Phase 1 검증 중 발견) — Phase 2는 elements의
                # span_start/span_end를 span 계산 루프와 element_id로 맞춰야
                # 하므로, 표도 다른 요소처럼 text_blocks에 한 항목을 남겨야
                # 한다. block_type="table"이라 parsed_text 조립 로직(기존
                # 정규식 구조분석의 [표 N] 마커 관례)과도 호환된다.
                page.text_blocks.append(
                    RawTextBlock(
                        text=markdown, page_number=page_no, bbox=bbox,
                        block_type="table", element_id=table_id,
                    )
                )
                elements.append({
                    "id": table_id, "page": page_no, "type": "table", "bbox": bbox,
                    "content": {"text": markdown, "markdown": markdown},
                    "metadata": {
                        "section_path": list(section_path), "is_header": False,
                        "is_footer": False, "confidence": 1.0, "detected_as": "docling_table",
                        # 메타 정보 생성 설계서(2026-07-23) Phase 3 — rows는 이미
                        # 위에서 계산돼 있어 재계산 없이 그대로 재사용.
                        "order": len(elements), "is_caption": False,
                        "table_rows": len(rows), "table_cols": len(rows[0]) if rows else 0,
                        "style": None,
                    },
                })
                continue

            if label in _PICTURE_LABELS:
                # _recognize_document_images(process.py)가 image_bytes로
                # 실제 그림을 인식/저장한다 — bytes가 없으면(구버전 코드) 항상
                # 스킵되어 요소/구조 탭엔 그림이 보이는데 그림 탭은 늘 비어 있다.
                # RGBA/팔레트 모드는 그대로
                # PNG로 저장하고, 흰 배경 합성 등 모드 변환은 기존
                # _recognize_document_images가 이미 처리한다.
                image_bytes = None
                try:
                    pil_image = item.get_image(doc)
                    if pil_image is not None:
                        buf = io.BytesIO()
                        pil_image.save(buf, format="PNG")
                        image_bytes = buf.getvalue()
                except Exception:
                    image_bytes = None
                page.image_regions.append(
                    RawImageRegion(page_number=page_no, bbox=bbox or (0, 0, 0, 0), image_bytes=image_bytes)
                )
                elements.append({
                    "id": str(uuid4()), "page": page_no, "type": "picture", "bbox": bbox,
                    "content": {"text": "", "markdown": ""},
                    "metadata": {
                        "section_path": list(section_path), "is_header": False, "is_footer": False,
                        # 메타 정보 생성 설계서(2026-07-23) Phase 3 — image_path는
                        # Document.images가 이 시점(어댑터 extract() 실행 중)에는
                        # 아직 계산되지 않았으므로 여기서 채울 수 없다. 이미지
                        # 인식이 끝난 뒤 extraction_blocks.py::TextExtractBlock이
                        # 페이지 번호로 매치해 채운다.
                        "order": len(elements), "is_caption": False, "style": None,
                        "image_path": None,
                    },
                })
                continue

            text = (getattr(item, "text", "") or "").strip()
            is_header = label in _HEADER_LABELS
            is_footer = label in _FOOTER_LABELS
            block_type = "header" if is_header else "footer" if is_footer else "paragraph"
            element_id = str(uuid4())

            if text:
                page.text_blocks.append(
                    RawTextBlock(
                        text=text, page_number=page_no, bbox=bbox, block_type=block_type,
                        element_id=element_id,
                    )
                )

            if label in _HEADING_LABELS:
                section_path = [text] if text else section_path

            metadata = {
                "section_path": list(section_path), "is_header": is_header, "is_footer": is_footer,
                # 메타 정보 생성 설계서(2026-07-23) Phase 3 — order는 순회
                # 인덱스(읽기 순서), style/font_size/font_name은 Docling이
                # 제공하지 않아 항상 None(자동 생성 불가, 스키마에는 노출).
                "order": len(elements), "is_caption": label in _CAPTION_LABELS, "style": None,
            }
            if label in _HEADING_LABELS:
                # DocumentNode.level 계층 구성에 필요(Phase 2) — Docling의
                # SectionHeaderItem.level이 곧 우리의 heading depth.
                metadata["level"] = getattr(item, "level", None)

            elements.append({
                "id": element_id, "page": page_no, "type": label, "bbox": bbox,
                "content": {"text": text, "markdown": text},
                "metadata": metadata,
            })

        line_layout = [
            {
                "page_number": el["page"], "text": el["content"]["text"],
                "bbox": el["bbox"], "font_size": None, "is_bold": el["type"] in _HEADING_LABELS,
                "is_italic": False, "style_name": el["type"],
            }
            for el in elements
            if el["type"] not in _TABLE_LABELS and el["type"] not in _PICTURE_LABELS
        ]

        pages = [pages_by_no[no] for no in sorted(pages_by_no)]
        ocr_used = any(getattr(item, "confidence", None) is not None for item, _ in doc.iterate_items())

        return RawParsedDocument(
            format_id="pdf",
            page_count=len(pages),
            pages=pages,
            metadata={"ocr_used": ocr_used, "line_layout": line_layout, "elements": elements},
            warnings=warnings,
        )

    def extract_metadata(self, file_path: Path) -> dict:
        return {}
