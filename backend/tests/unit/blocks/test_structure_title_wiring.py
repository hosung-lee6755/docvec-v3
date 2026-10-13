"""structure_analyze 가 제목을 정하는 연결부 — 레이아웃/블록에서 표지 줄을 만들고, 사용자가 고친 제목은 지킨다."""
from types import SimpleNamespace

from app.pipeline.blocks import structure_blocks as sb


def make_doc(**overrides):
    base = dict(
        title=None, original_filename="x.pdf", filename="x.pdf", source_title=None, ocr_used=False,
        extraction_layout=None, user_edited_fields=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def block(node_type, text):
    return (node_type, 1 if node_type == "HEADING" else None, 0, len(text), text, None)


def test_title_comes_from_page_one_layout_not_first_heading():
    doc = make_doc(
        original_filename="01.(사례집)개인하수처리시설.pdf",
        extraction_layout=[
            {"page_number": 1, "text": "2025", "style_name": "section_header"},
            {"page_number": 1, "text": "경기도데이터분석 사례집", "style_name": "section_header"},
            {"page_number": 2, "text": "효율적인 점검대상선정", "style_name": "section_header"},
        ],
    )

    sb._apply_document_title(doc, [block("HEADING", "2025")])

    assert doc.title == "경기도데이터분석 사례집"


def test_docx_font_sizes_are_used_from_layout():
    doc = make_doc(
        original_filename="AIDE_디구루_AI검수기준서_v1.3.docx",
        extraction_layout=[
            {"page_number": 1, "text": "AIDE", "font_size": 10.0, "style_name": "Normal"},
            {"page_number": 1, "text": "AI 외주(디구루) Driver DNA™ Prototype", "font_size": 16.0, "style_name": "Normal"},
            {"page_number": 1, "text": "성과물 검수 기준서", "font_size": 21.0, "style_name": "Normal"},
            {"page_number": 1, "text": "Acceptance Criteria", "font_size": 9.5, "style_name": "Normal"},
        ],
    )

    sb._apply_document_title(doc, [])

    assert doc.title == "AI 외주(디구루) Driver DNA™ Prototype 성과물 검수 기준서"


def test_without_layout_lead_lines_come_from_the_first_blocks():
    doc = make_doc(original_filename="AI 기반 UIUX 개선 컨설팅 보고서_v1.0.hwpx")
    blocks = [
        block("PARAGRAPH", "범정부 UI/UX 디자인시스템 고도화 및 운영관리"),
        block("PARAGRAPH", "AI 기반 UI/UX 개선"),
        block("PARAGRAPH", "컨설팅 보고서"),
        block("PARAGRAPH", "2025년 12월"),
        block("HEADING", "1. 사업개요"),
    ]

    sb._apply_document_title(doc, blocks)

    assert doc.title == "범정부 UI/UX 디자인시스템 고도화 및 운영관리 AI 기반 UI/UX 개선 컨설팅 보고서"


def test_chapter_heading_is_never_the_title_falls_back_to_filename():
    doc = make_doc(original_filename="정형데이터 기반_AX사례_에너지 효율 및 수요 예측_20260211.pdf")

    sb._apply_document_title(doc, [block("HEADING", "2. AX 사례")])

    assert doc.title == "정형데이터 기반 AX사례 에너지 효율 및 수요 예측"


def test_embedded_title_property_is_used():
    doc = make_doc(source_title="AI Servor 기능 소개서", original_filename="AI_Servor_소개서.pdf")

    sb._apply_document_title(doc, [block("HEADING", "AI Servor")])

    assert doc.title == "AI Servor 기능 소개서"


def test_user_edited_title_is_not_overwritten():
    doc = make_doc(title="내가 정한 제목", user_edited_fields=["title"], source_title="AI Servor 기능 소개서")

    sb._apply_document_title(doc, [block("HEADING", "AI Servor")])

    assert doc.title == "내가 정한 제목"


def test_other_edited_fields_do_not_block_title_regeneration():
    doc = make_doc(title="낡은 제목", user_edited_fields=["category"], source_title="AI Servor 기능 소개서")

    sb._apply_document_title(doc, [])

    assert doc.title == "AI Servor 기능 소개서"
