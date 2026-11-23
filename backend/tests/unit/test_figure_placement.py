"""그림 글의 자리와 로컬 그림 설명(전체 점검 2-1)."""
import base64
import io
import json
import os
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.pipeline.adapters.base import RawImageRegion, RawPage, RawParsedDocument, RawTextBlock
from app.pipeline.tasks import process as proc
from app.services.llm import LLMServerError, LLMServerProvider

LONG_TEXT = "그림에 담긴 충분히 긴 설명"


def _png(seed: int = 0) -> bytes:
    from PIL import Image

    image = Image.frombytes("RGB", (100, 100), os.urandom(100 * 100 * 3))
    image.putpixel((0, 0), (seed, seed, seed))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _block(text, top, bottom):
    return RawTextBlock(text=text, page_number=1, bbox=(0, top, 100, bottom))


def _parsed(blocks, regions):
    page = RawPage(page_number=1, width=600, height=800, text_blocks=blocks, table_candidates=[],
                   image_regions=regions)
    return RawParsedDocument(format_id="x", page_count=1, pages=[page], metadata={}, warnings=[])


def _run(parsed):
    with patch("app.services.storage.storage_service", MagicMock()), \
         patch.object(proc, "_recognize_figure_text", return_value=LONG_TEXT):
        proc._recognize_document_images("doc", parsed, {})
    return [block.text.split("\n")[0] for block in parsed.pages[0].text_blocks]


def test_figure_text_goes_right_after_the_paragraph_above_it():
    blocks = [_block("첫 문단", 100, 150), _block("둘째 문단", 400, 450)]
    region = RawImageRegion(page_number=1, bbox=(0, 200, 100, 350), image_bytes=_png())

    assert _run(_parsed(blocks, [region])) == ["첫 문단", "[그림 1]", "둘째 문단"]


def test_bottom_left_origin_coordinates_are_read_the_right_way_up():
    # 왼쪽 아래 원점: 값이 클수록 위. 첫 문단이 쪽 위쪽에 있다
    blocks = [_block("첫 문단", 700, 650), _block("둘째 문단", 400, 350)]
    region = RawImageRegion(page_number=1, bbox=(0, 600, 100, 450), image_bytes=_png())

    assert _run(_parsed(blocks, [region])) == ["첫 문단", "[그림 1]", "둘째 문단"]


def test_figure_above_all_text_goes_first():
    blocks = [_block("본문", 300, 350)]
    region = RawImageRegion(page_number=1, bbox=(0, 50, 100, 200), image_bytes=_png())

    assert _run(_parsed(blocks, [region])) == ["[그림 1]", "본문"]


def test_two_figures_under_the_same_paragraph_keep_their_order():
    blocks = [_block("첫 문단", 100, 150), _block("둘째 문단", 700, 750)]
    regions = [
        RawImageRegion(page_number=1, bbox=(0, 200, 100, 300), image_bytes=_png(1)),
        RawImageRegion(page_number=1, bbox=(0, 400, 100, 500), image_bytes=_png(2)),
    ]

    assert _run(_parsed(blocks, regions)) == ["첫 문단", "[그림 1]", "[그림 2]", "둘째 문단"]


def test_unknown_position_still_appends_at_the_end_of_the_page():
    blocks = [RawTextBlock(text="본문", page_number=1)]
    region = RawImageRegion(page_number=1, bbox=(0, 0, 0, 0), image_bytes=_png())

    assert _run(_parsed(blocks, [region])) == ["본문", "[그림 1]"]


def test_local_vision_is_skipped_when_not_configured(monkeypatch):
    monkeypatch.setattr(proc.settings, "local_vision_model", "")

    assert proc._describe_figure_locally(b"png") == ""


def test_local_vision_failure_falls_back_quietly(monkeypatch):
    monkeypatch.setattr(proc.settings, "local_vision_model", "vision-model")
    provider = MagicMock()
    provider.generate_vision.side_effect = RuntimeError("server down")
    monkeypatch.setattr(proc, "_local_vision_providers", {"vision-model": provider})

    assert proc._describe_figure_locally(b"png") == ""


def test_local_vision_failure_releases_the_model_so_the_next_figure_starts_clean(monkeypatch):
    monkeypatch.setattr(proc.settings, "local_vision_model", "vision-model")
    provider = MagicMock()
    provider.generate_vision.side_effect = RuntimeError("prediction aborted, token repeat limit reached")
    monkeypatch.setattr(proc, "_local_vision_providers", {"vision-model": provider})

    assert proc._describe_figure_locally(b"png") == ""
    provider.release.assert_called_once()


def test_local_vision_degenerate_output_is_dropped_and_the_model_released(monkeypatch):
    monkeypatch.setattr(proc.settings, "local_vision_model", "vision-model")
    provider = MagicMock()
    provider.generate_vision.return_value = "G" * 100
    monkeypatch.setattr(proc, "_local_vision_providers", {"vision-model": provider})

    assert proc._describe_figure_locally(b"png") == ""
    provider.release.assert_called_once()


def test_local_vision_normal_output_keeps_the_model_loaded(monkeypatch):
    monkeypatch.setattr(proc.settings, "local_vision_model", "vision-model")
    provider = MagicMock()
    provider.generate_vision.return_value = "행정안전부 로고"
    monkeypatch.setattr(proc, "_local_vision_providers", {"vision-model": provider})

    assert proc._describe_figure_locally(b"png") == "행정안전부 로고"
    provider.release.assert_not_called()


def test_server_provider_release_unloads_the_model():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={})

    LLMServerProvider("vision-model", transport=httpx.MockTransport(handler)).release()

    assert seen == {"path": "/api/generate", "model": "vision-model", "keep_alive": 0}


def test_server_provider_release_does_not_raise_when_the_server_is_down():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    LLMServerProvider("vision-model", transport=httpx.MockTransport(handler)).release()


def test_server_provider_error_message_carries_the_server_reason():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "prediction aborted, token repeat limit reached"})

    provider = LLMServerProvider("vision-model", transport=httpx.MockTransport(handler))

    with pytest.raises(LLMServerError, match="token repeat limit"):
        provider.generate_vision("", b"png", "image/png", "설명")


def test_local_vision_result_is_used_before_ocr(monkeypatch):
    monkeypatch.setattr(proc.settings, "local_vision_model", "vision-model")
    provider = MagicMock()
    provider.generate_vision.return_value = " 매출 추이를 보여 주는 막대 그래프 "
    monkeypatch.setattr(proc, "_local_vision_providers", {"vision-model": provider})

    assert proc._recognize_figure_text(b"png", {}) == "매출 추이를 보여 주는 막대 그래프"


def test_server_provider_sends_the_image_as_base64():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": "설명"}})

    provider = LLMServerProvider("vision-model", transport=httpx.MockTransport(handler))

    assert provider.generate_vision("", b"raw-bytes", "image/png", "설명해 주세요") == "설명"
    assert seen["model"] == "vision-model" and seen["stream"] is False
    assert seen["messages"] == [
        {"role": "user", "content": "설명해 주세요", "images": [base64.b64encode(b"raw-bytes").decode()]},
    ]


def test_figure_text_block_carries_the_picture_element_id():
    # Docling 경로: 그림 글이 그림 요소 id를 이어받아야 구조 노드가 그 글의 위치를 갖고 청크에 들어간다(2026-11-20)
    blocks = [_block("첫 문단", 100, 150)]
    region = RawImageRegion(page_number=1, bbox=(0, 200, 100, 350), image_bytes=_png(), element_id="pic-1")
    parsed = _parsed(blocks, [region])

    _run(parsed)

    figure = parsed.pages[0].text_blocks[1]
    assert figure.text.startswith("[그림 1]")
    assert figure.element_id == "pic-1"


def test_tesseract_figure_text_drops_low_confidence_lines(monkeypatch):
    # 정민산업 에너지진단보고서 차트(2026-11-23): "wise waso22 45" 같은 저신뢰 줄을 그림 글에서 뺀다
    import sys
    from types import SimpleNamespace

    fake = SimpleNamespace(
        Output=SimpleNamespace(DICT="dict"),
        image_to_string=lambda image, lang, config: "Air COMP. 계통도\nwise waso22 45\n",
        image_to_data=lambda image, lang, config, output_type: {
            "text": ["Air", "COMP.", "계통도", "wise", "waso22", "45"],
            "conf": [95, 90, 88, 10, 2, 5],
            "block_num": [1, 1, 1, 1, 1, 1], "par_num": [1, 1, 1, 1, 1, 1], "line_num": [1, 1, 1, 2, 2, 2],
        },
    )
    monkeypatch.setitem(sys.modules, "pytesseract", fake)
    monkeypatch.setattr(proc.settings, "local_vision_model", "")

    assert proc._recognize_figure_text(_png(), {}) == "Air COMP. 계통도"
