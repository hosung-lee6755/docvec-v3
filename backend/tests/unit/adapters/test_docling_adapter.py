"""DoclingAdapter 단위 테스트 — 실제 `docling` 패키지는 아직 이 개발 컨테이너에
설치돼 있지 않으므로(Phase 1의 Dockerfile.worker 리빌드가 별도 인프라 단계),
`sys.modules`에 최소 shape의 fake 모듈을 주입해 우리 쪽 매핑 로직만 검증한다.
실제 docling 패키지 설치 후에는 이 fake와 실제 API가 어긋나지 않는지 별도로
재검증해야 한다(Docling 도입 설계서, 2026-07-23 Phase 1)."""
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest


class _FakeBBox:
    def __init__(self, l, t, r, b):
        self.l, self.t, self.r, self.b = l, t, r, b


class _FakeProv:
    def __init__(self, page_no, bbox):
        self.page_no = page_no
        self.bbox = bbox


class _FakeLabel:
    def __init__(self, value):
        self.value = value


class _FakeTextItem:
    def __init__(self, text, label, page_no, bbox=(0, 0, 100, 10), level=None):
        self.text = text
        self.label = _FakeLabel(label)
        self.prov = [_FakeProv(page_no, _FakeBBox(*bbox))]
        if level is not None:
            self.level = level


class _FakeDataFrame:
    def __init__(self, columns, rows):
        self.columns = columns
        self._rows = rows

    def itertuples(self, index=False):
        return iter(self._rows)


class _FakeTableItem:
    def __init__(self, rows, page_no, bbox=(0, 20, 100, 40)):
        self.label = _FakeLabel("table")
        self.prov = [_FakeProv(page_no, _FakeBBox(*bbox))]
        self._rows = rows

    def export_to_dataframe(self):
        return _FakeDataFrame(self._rows[0], self._rows[1:])


class _FakeImage:
    """PIL.Image 최소 fake — .save(buf, format=...)만 필요."""

    def __init__(self, payload=b"\x89PNG\r\n\x1a\nFAKEDATA"):
        self._payload = payload

    def save(self, buf, format=None):
        buf.write(self._payload)


class _FakePictureItem:
    def __init__(self, page_no, bbox=(0, 40, 100, 90), image=None):
        self.label = _FakeLabel("picture")
        self.prov = [_FakeProv(page_no, _FakeBBox(*bbox))]
        self._image = image

    def get_image(self, doc):
        return self._image


class _FakeDoclingDocument:
    def __init__(self, items):
        self._items = items
        self.pages = {}

    def iterate_items(self):
        return iter(self._items)


class _FakeConvertResult:
    def __init__(self, document):
        self.document = document


@pytest.fixture
def fake_docling_module(monkeypatch):
    """`docling.datamodel.base_models`/`pipeline_options`/`document_converter`를
    최소 fake로 sys.modules에 등록하고, DocumentConverter 생성자에 넘어간
    kwargs를 캡처할 수 있게 mock을 반환한다."""
    captured = {}

    base_models_mod = types.ModuleType("docling.datamodel.base_models")
    base_models_mod.InputFormat = types.SimpleNamespace(PDF="pdf")

    pipeline_options_mod = types.ModuleType("docling.datamodel.pipeline_options")

    class _FakeEasyOcrOptions:
        def __init__(self, lang):
            self.lang = lang

    class _FakePdfPipelineOptions:
        def __init__(self):
            self.do_ocr = False
            self.ocr_options = None
            self.generate_picture_images = False

    pipeline_options_mod.EasyOcrOptions = _FakeEasyOcrOptions
    pipeline_options_mod.PdfPipelineOptions = _FakePdfPipelineOptions

    document_converter_mod = types.ModuleType("docling.document_converter")

    class _FakePdfFormatOption:
        def __init__(self, pipeline_options):
            self.pipeline_options = pipeline_options

    class _FakeDocumentConverter:
        def __init__(self, format_options):
            captured["format_options"] = format_options

        def convert(self, path):
            captured["convert_path"] = path
            return _FakeConvertResult(captured["fake_document"])

    document_converter_mod.PdfFormatOption = _FakePdfFormatOption
    document_converter_mod.DocumentConverter = _FakeDocumentConverter

    docling_mod = types.ModuleType("docling")
    datamodel_mod = types.ModuleType("docling.datamodel")

    monkeypatch.setitem(sys.modules, "docling", docling_mod)
    monkeypatch.setitem(sys.modules, "docling.datamodel", datamodel_mod)
    monkeypatch.setitem(sys.modules, "docling.datamodel.base_models", base_models_mod)
    monkeypatch.setitem(sys.modules, "docling.datamodel.pipeline_options", pipeline_options_mod)
    monkeypatch.setitem(sys.modules, "docling.document_converter", document_converter_mod)

    return captured


def test_easyocr_korean_option_is_passed_not_default_rapidocr(fake_docling_module, tmp_path):
    from app.pipeline.adapters.docling_adapter import DoclingAdapter

    fake_docling_module["fake_document"] = _FakeDoclingDocument([])
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    DoclingAdapter().extract(pdf_path, {})

    pipeline_options = fake_docling_module["format_options"]["pdf"].pipeline_options
    assert pipeline_options.do_ocr is True
    assert pipeline_options.ocr_options.lang == ["ko"]


def test_elements_and_legacy_fields_built_from_docling_items(fake_docling_module, tmp_path):
    from app.pipeline.adapters.docling_adapter import DoclingAdapter

    items = [
        (_FakeTextItem("1. 개요", "section_header", page_no=1, level=2), 0),
        (_FakeTextItem("본문 문단입니다.", "text", page_no=1), 1),
        (_FakeTableItem([["Name", "Age"], ["Kim", "20"]], page_no=1), 1),
    ]
    fake_docling_module["fake_document"] = _FakeDoclingDocument(items)
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    parsed = DoclingAdapter().extract(pdf_path, {})

    elements = parsed.metadata["elements"]
    assert [el["type"] for el in elements] == ["section_header", "text", "table"]
    assert elements[0]["content"]["text"] == "1. 개요"
    assert elements[0]["metadata"]["level"] == 2
    assert elements[1]["metadata"]["section_path"] == ["1. 개요"]
    assert "level" not in elements[1]["metadata"]

    table_el = elements[2]
    assert "| Name | Age |" in table_el["content"]["markdown"]
    assert "| Kim | 20 |" in table_el["content"]["markdown"]

    assert parsed.page_count == 1
    page = parsed.pages[0]
    assert len(page.table_candidates) == 1
    assert page.table_candidates[0].rows == [["Name", "Age"], ["Kim", "20"]]

    # 문서 파싱 고도화 Phase 2 — 표도 이제 다른 요소처럼 text_blocks에 마커를
    # 남긴다(그래야 extraction_blocks.py의 span 계산에서 표가 누락되지 않는다).
    assert [b.text for b in page.text_blocks] == [
        "1. 개요", "본문 문단입니다.", table_el["content"]["markdown"],
    ]
    # element_id는 elements 리스트의 "id"와 정확히 일치해야 span 되찾기가 된다.
    assert [b.element_id for b in page.text_blocks] == [
        elements[0]["id"], elements[1]["id"], table_el["id"],
    ]

    line_layout = parsed.metadata["line_layout"]
    assert [line["text"] for line in line_layout] == ["1. 개요", "본문 문단입니다."]


def test_generate_picture_images_enabled(fake_docling_module, tmp_path):
    from app.pipeline.adapters.docling_adapter import DoclingAdapter

    fake_docling_module["fake_document"] = _FakeDoclingDocument([])
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    DoclingAdapter().extract(pdf_path, {})

    pipeline_options = fake_docling_module["format_options"]["pdf"].pipeline_options
    assert pipeline_options.generate_picture_images is True


def test_picture_item_image_bytes_captured_from_get_image(fake_docling_module, tmp_path):
    """그림 탭 표출 버그(2026-07-25) 회귀 테스트 — image_bytes가 채워지지
    않으면 _recognize_document_images(process.py)가 항상 스킵해 Document.images가
    비어, 구조/요소 탭엔 그림이 보이는데 그림 탭만 항상 비어 보였다."""
    from app.pipeline.adapters.docling_adapter import DoclingAdapter

    items = [(_FakePictureItem(page_no=1, image=_FakeImage()), 0)]
    fake_docling_module["fake_document"] = _FakeDoclingDocument(items)
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    parsed = DoclingAdapter().extract(pdf_path, {})

    page = parsed.pages[0]
    assert len(page.image_regions) == 1
    assert page.image_regions[0].image_bytes == b"\x89PNG\r\n\x1a\nFAKEDATA"
    assert parsed.metadata["elements"][0]["type"] == "picture"


def test_picture_item_image_bytes_none_when_get_image_returns_none(fake_docling_module, tmp_path):
    from app.pipeline.adapters.docling_adapter import DoclingAdapter

    items = [(_FakePictureItem(page_no=1, image=None), 0)]
    fake_docling_module["fake_document"] = _FakeDoclingDocument(items)
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    parsed = DoclingAdapter().extract(pdf_path, {})

    assert parsed.pages[0].image_regions[0].image_bytes is None


class _FakePixmap:
    def tobytes(self, fmt):
        return b"FAKE_PAGE_PNG"


class _FakeFitzPage:
    def get_pixmap(self, dpi=300):
        return _FakePixmap()


class _FakeFitzDoc:
    def __getitem__(self, idx):
        return _FakeFitzPage()

    def close(self):
        pass


@pytest.fixture
def fake_fitz_module(monkeypatch):
    """docling_adapter._escalate_low_coverage_pages는 함수 내부에서 지연
    import로 fitz(pymupdf)를 불러온다 — pdf_adapter.py의 기존 VLM OCR 폴백과
    동일하게 페이지를 PNG로 렌더링하는 용도라 실제 PDF 렌더링 없이 최소
    fake로 검증한다."""
    fitz_mod = types.ModuleType("fitz")
    fitz_mod.open = lambda path: _FakeFitzDoc()
    monkeypatch.setitem(sys.modules, "fitz", fitz_mod)
    return fitz_mod


# 서울시 도시 범죄 취약지 분석 PDF 실증(2026-07-29)에서 확인된 케이스와
# 동일하게, 그림이 페이지 전체를 덮어 텍스트가 거의 없는 페이지를 재현한다.
_NEAR_FULL_PAGE_PICTURE_BBOX = (0, 0, 100, 95)


def test_low_coverage_page_escalates_to_vlm_when_key_registered(
    fake_docling_module, fake_fitz_module, tmp_path, monkeypatch,
):
    from app.pipeline.adapters.docling_adapter import DoclingAdapter

    items = [(_FakePictureItem(page_no=1, bbox=_NEAR_FULL_PAGE_PICTURE_BBOX, image=None), 0)]
    fake_docling_module["fake_document"] = _FakeDoclingDocument(items)
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    monkeypatch.setattr(
        "app.pipeline.adapters.pdf_adapter._cloud_vlm_ocr",
        lambda image_bytes, backend, key: "인포그래픽 본문을 옮겨 적은 텍스트입니다.",
    )

    parsed = DoclingAdapter().extract(
        pdf_path, {"vision_backend": "openai", "vision_api_key": "test-key"},
    )

    vlm_blocks = [b for b in parsed.pages[0].text_blocks if b.block_type == "vlm_ocr"]
    assert len(vlm_blocks) == 1
    assert vlm_blocks[0].text == "인포그래픽 본문을 옮겨 적은 텍스트입니다."

    vlm_elements = [el for el in parsed.metadata["elements"] if el["type"] == "vlm_ocr"]
    assert len(vlm_elements) == 1
    assert vlm_elements[0]["metadata"]["detected_as"] == "cloud_vlm_ocr"
    assert parsed.metadata["ocr_used"] is True


def test_no_escalation_without_registered_vision_key(fake_docling_module, tmp_path, monkeypatch):
    """BYOK 키가 없으면(_resolve_vision_credentials가 {} 반환, process.py)
    options에 vision_backend/vision_api_key가 아예 없다 — 기존 EasyOCR-only
    동작과 완전히 동일해야 하고, fitz/클라우드 호출이 시도조차 되면 안 된다."""
    from app.pipeline.adapters.docling_adapter import DoclingAdapter

    items = [(_FakePictureItem(page_no=1, bbox=_NEAR_FULL_PAGE_PICTURE_BBOX, image=None), 0)]
    fake_docling_module["fake_document"] = _FakeDoclingDocument(items)
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    def _boom(*args, **kwargs):
        raise AssertionError("vision credentials가 없으면 _cloud_vlm_ocr가 호출되면 안 된다")

    monkeypatch.setattr("app.pipeline.adapters.pdf_adapter._cloud_vlm_ocr", _boom)

    parsed = DoclingAdapter().extract(pdf_path, {})

    assert [b.block_type for b in parsed.pages[0].text_blocks] == []
    assert not any(el["type"] == "vlm_ocr" for el in parsed.metadata["elements"])
