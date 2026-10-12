"""OCR 설정 회귀 테스트 — 값은 scripts/ocr_benchmark.py 실측(32쪽, 검색 hit@1 0.30→0.68)으로 정했다.

설정을 바꿀 때는 이 값이 아니라 벤치마크를 다시 돌려 근거를 확인해야 한다(docs/유지보수_가이드.md 참고).
"""
from PIL import Image

from app.pipeline.adapters import pdf_adapter


def test_tesseract_uses_psm4_single_column_segmentation():
    # psm3(자동)은 한글 스캔에서 글자 벌어짐(한 글자 토큰 40%)이 심해 검색 가능한 텍스트가 안 나온다.
    assert "--psm 4" in pdf_adapter._TESSERACT_CONFIG
    assert "--oem 1" in pdf_adapter._TESSERACT_CONFIG


def test_preprocess_keeps_grayscale_instead_of_binarizing():
    # 이진화(Otsu)는 벤치마크에서 이득이 없었고 흐린 글자를 지운다.
    image = Image.new("RGB", (40, 40), (200, 200, 200))
    image.putpixel((5, 5), (90, 90, 90))

    result = pdf_adapter._preprocess_for_ocr(image)

    assert result.mode == "L"
    assert len(set(result.getdata())) > 1
    assert set(result.getdata()) != {0, 255}
