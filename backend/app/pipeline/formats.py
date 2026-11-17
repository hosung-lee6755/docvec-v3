"""올릴 수 있는 문서 형식(전체 점검 1-2, 2026-11-16).

업로드, 커넥터 동기화, 파일 검증 블록이 같은 목록을 쓴다. 형식을 더할 때는 여기와
adapters/__init__.py의 get_adapter만 고친다.
"""
from pathlib import PurePath

IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"})
PLAIN_TEXT_SUFFIXES = frozenset({".txt", ".md", ".html", ".htm"})

# MinIO에 저장할 Content-Type. 원본은 앱과 다른 출처에서 인라인으로 열리므로 HTML과 마크다운도
# text/plain으로 저장한다. text/html로 저장하면 올린 파일 안의 스크립트가 그 출처에서 실행된다.
EXTENSION_CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".hwp": "application/x-hwp",
    ".hwpx": "application/haansofthwpx",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".txt": "text/plain",
    ".md": "text/plain",
    ".html": "text/plain",
    ".htm": "text/plain",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".bmp": "image/bmp",
    ".webp": "image/webp",
}

SUPPORTED_SUFFIXES = frozenset(EXTENSION_CONTENT_TYPES)
SUPPORTED_LABEL = "PDF, DOCX, HWP, HWPX, XLSX, PPTX, TXT, MD, HTML, 이미지(PNG, JPG, TIFF, BMP, WEBP)"


def suffix_of(filename: str) -> str:
    return PurePath(filename).suffix.lower()


def is_supported(filename: str) -> bool:
    return suffix_of(filename) in SUPPORTED_SUFFIXES
