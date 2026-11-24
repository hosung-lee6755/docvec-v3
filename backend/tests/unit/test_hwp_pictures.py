"""HWP·HWPX 그림을 본문에 박힌 자리에 둔다(2026-11-23).

브라우저 점검에서 NS-AM 검사매뉴얼의 그림 20·23·24·29·33 글이 모두 1쪽 표지 바로 뒤에 붙어 있었다.
어댑터가 BinData 그림을 위치 없이 읽어 모두 1쪽에 두었기 때문이다. 그림 컨트롤이 가리키는 BinData 를 읽어
그림이 들어 있던 문단 뒤에 두고, 미리보기 쪽 나눔에서도 그 문단의 쪽을 따라가게 한다."""
import xml.etree.ElementTree as ET

from app.pipeline.adapters.base import RawImageRegion, RawPage, RawParsedDocument, RawTextBlock
from app.pipeline.adapters.hwp_pictures import (
    anchored_image_regions,
    hwp_bin_stems,
    hwp_picture_refs,
    hwpx_manifest_stems,
    hwpx_picture_refs,
)

HC = "http://www.hancom.co.kr/hwpml/2011/core"
HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"


def test_hwp_bindata_ids_map_to_their_storage_stream_names():
    root = ET.fromstring(
        "<HwpDoc><DocInfo><IdMappings>"
        '<BinData storage="link"/>'
        '<BinData storage="embedding"><BinDataEmbedding storage-id="BIN0002" ext="jpg"/></BinData>'
        '<BinData storage="embedding"><BinDataEmbedding storage-id="BIN0003" ext="bmp"/></BinData>'
        "</IdMappings></DocInfo></HwpDoc>"
    )

    assert hwp_bin_stems(root) == {"2": "BIN0002", "3": "BIN0003"}


def test_hwp_picture_refs_follow_document_order_inside_a_control():
    control = ET.fromstring(
        "<GShapeObjectControl><ShapeComponent><ShapePicture>"
        '<PictureInfo bindata-id="3"/></ShapePicture></ShapeComponent>'
        '<ShapeComponent><ShapePicture><PictureInfo bindata-id="2"/></ShapePicture></ShapeComponent>'
        '<ShapeComponent><ShapePicture><PictureInfo bindata-id="9"/></ShapePicture></ShapeComponent>'
        "</GShapeObjectControl>"
    )

    assert hwp_picture_refs(control, {"2": "BIN0002", "3": "BIN0003"}) == ["BIN0003", "BIN0002"]


def test_hwpx_picture_refs_and_manifest_ids():
    paragraph = ET.fromstring(
        f'<hp:p xmlns:hp="{HP}" xmlns:hc="{HC}"><hp:run><hp:pic><hc:img binaryItemIDRef="image2"/></hp:pic>'
        '<hp:pic><hc:img binaryItemIDRef="image1"/></hp:pic></hp:run></hp:p>'
    )
    manifest = (
        b'<opf:package xmlns:opf="http://www.idpf.org/2007/opf/"><opf:manifest>'
        b'<opf:item id="image1" href="BinData/image1.png" media-type="image/png"/>'
        b'<opf:item id="logo" href="BinData/image7.bmp" media-type="image/bmp"/>'
        b'<opf:item id="header" href="Contents/header.xml" media-type="application/xml"/>'
        b"</opf:manifest></opf:package>"
    )

    assert hwpx_picture_refs(paragraph) == ["image2", "image1"]
    assert hwpx_manifest_stems(manifest) == {"image1": "image1", "logo": "image7"}
    assert hwpx_manifest_stems(b"<not xml") == {}


def test_images_keep_their_anchor_and_unplaced_ones_go_last_without_one():
    first, second = RawTextBlock(text="첫 문단", page_number=1), RawTextBlock(text="둘째 문단", page_number=1)
    named = [("BIN0001", b"one"), ("BIN0002", b"two"), ("BIN0003", b"three")]
    refs = ["BIN0002", "BIN0001", "BIN0002", "BIN9999"]
    anchors = [(0, "start"), (1, second), (2, first), (3, first)]

    regions = anchored_image_regions(refs, anchors, named)

    assert [(r.image_bytes, r.anchor) for r in regions] == [
        (b"two", "start"), (b"one", second), (b"three", None),
    ]


def test_figure_text_follows_the_anchor_paragraph_of_its_picture():
    from unittest.mock import MagicMock, patch

    from app.pipeline.tasks import process as proc
    from tests.unit.test_figure_placement import LONG_TEXT, _png

    first, second = RawTextBlock(text="첫 문단", page_number=1), RawTextBlock(text="둘째 문단", page_number=1)
    regions = [
        RawImageRegion(page_number=1, bbox=(0, 0, 0, 0), image_bytes=_png(1), anchor=first),
        RawImageRegion(page_number=1, bbox=(0, 0, 0, 0), image_bytes=_png(2), anchor="start"),
    ]
    page = RawPage(page_number=1, width=595, height=842, text_blocks=[first, second], table_candidates=[],
                   image_regions=regions)
    parsed = RawParsedDocument(format_id="hwp", page_count=1, pages=[page], metadata={}, warnings=[])

    with patch("app.services.storage.storage_service", MagicMock()), \
         patch.object(proc, "_recognize_figure_text", return_value=LONG_TEXT):
        proc._recognize_document_images("doc", parsed, {})

    assert [b.text.split("\n")[0] for b in page.text_blocks] == ["[그림 2]", "첫 문단", "[그림 1]", "둘째 문단"]


def test_repagination_moves_each_picture_to_the_page_of_its_anchor_paragraph():
    from unittest.mock import patch

    from app.pipeline.tasks import process as proc

    cover, body = RawTextBlock(text="표지 제목", page_number=1), RawTextBlock(text="본문 둘째 쪽 문단", page_number=1)
    anchored = RawImageRegion(page_number=1, bbox=(0, 0, 0, 0), image_bytes=b"a", anchor=body)
    loose = RawImageRegion(page_number=1, bbox=(0, 0, 0, 0), image_bytes=b"b")
    page = RawPage(page_number=1, width=595, height=842, text_blocks=[cover, body], table_candidates=[],
                   image_regions=[anchored, loose])
    parsed = RawParsedDocument(format_id="hwp", page_count=1, pages=[page], metadata={}, warnings=[])
    pages_text = [{"page_number": 1, "text": "표지 제목"}, {"page_number": 2, "text": "본문 둘째 쪽 문단"}]

    with patch("app.services.preview_service.preview_url_for"), \
         patch("app.services.preview_service.pdf_pages_text_for", return_value=pages_text):
        proc._repaginate_hwp_like("doc", type("Doc", (), {"filename": "a.hwp", "minio_key": "k"})(), parsed)

    by_page = {p.page_number: [r.image_bytes for r in p.image_regions] for p in parsed.pages}
    assert by_page == {1: [b"b"], 2: [b"a"]}
    assert anchored.page_number == 2
