"""title_resolver — 실제 문서 17건의 1쪽 데이터에서 뽑은 정답 사례로 제목 판정을 검증한다.

과거 방식("트리의 첫 HEADING")은 표지의 연도·머리글·장 제목을 제목으로 삼았다(사례집 "2025",
UIUX 보고서 "1. 사업개요", AX 사례 "2. AX 사례" 등)."""
import pytest

from app.pipeline.blocks.title_resolver import (
    LeadLine,
    clean_filename_title,
    is_usable_embedded_title,
    resolve_title,
)


def lines(*items):
    """("텍스트", 크기|None, 제목여부) 튜플 또는 문자열 → LeadLine 목록."""
    out = []
    for item in items:
        if isinstance(item, str):
            out.append(LeadLine(text=item))
            continue
        text = item[0]
        size = item[1] if len(item) > 1 else None
        heading = item[2] if len(item) > 2 else False
        out.append(LeadLine(text=text, size=size, is_heading=heading))
    return out


# ----------------------------------------------------------------- 파일명 정리
@pytest.mark.parametrize("filename, expected", [
    ("01_빅데이터 기반 심야버스 노선 수립을 위한 분석(요약본).pdf", "빅데이터 기반 심야버스 노선 수립을 위한 분석(요약본)"),
    ("AIDE_AI플랫폼_구축제안서_v2.docx", "AIDE AI플랫폼 구축제안서"),
    ("260416_2026년도_자율형공장_구축_지원사업_2차_공고.pdf", "2026년도 자율형공장 구축 지원사업 2차 공고"),
    ("디지털 정부서비스 UIUX가이드라인 [240709].pdf", "디지털 정부서비스 UIUX가이드라인"),
    ("[서울 데이터 펠로우십]서울시 도시 범죄 취약지 분석 및 억제 방안연구.pdf", "서울시 도시 범죄 취약지 분석 및 억제 방안연구"),
    ("정형데이터 기반_AX사례_에너지 효율 및 수요 예측_20260211.pdf", "정형데이터 기반 AX사례 에너지 효율 및 수요 예측"),
    ("AI 기반 UIUX 개선 컨설팅 보고서_v1.0.hwpx", "AI 기반 UIUX 개선 컨설팅 보고서"),
    ("1.에너지진단보고서_세원화성.pdf", "에너지진단보고서 세원화성"),
])
def test_clean_filename_title(filename, expected):
    assert clean_filename_title(filename) == expected


# ------------------------------------------------------------ 내장 제목 속성
@pytest.mark.parametrize("title", [
    None, "", " ", "4", "PowerPoint 프레젠테이션", "Microsoft Word - 보고서.docx", "Untitled",
    "제목 없음", "Ð\x08ÀÄèôà˝_8ÐT1.hwp", "report.pdf",
])
def test_unusable_embedded_titles_are_rejected(title):
    assert not is_usable_embedded_title(title, "x.pdf")


@pytest.mark.parametrize("title", ["AI Servor 기능 소개서", "AIDE 디구루 Driver DNA Prototype 성과물 검수 기준서 v1.3"])
def test_usable_embedded_titles_are_accepted(title):
    assert is_usable_embedded_title(title, "x.pdf")


def test_embedded_title_wins_over_cover_lines():
    got = resolve_title(
        lines(("AI Servor", None, True), ("평탄화 교정의 암묵지를", None, True)),
        filename="AI_Servor_소개서.pdf", embedded_title="AI Servor 기능 소개서",
    )
    assert got == "AI Servor 기능 소개서"


# ------------------------------------------------------- 표지 줄에서 제목 찾기
def test_year_only_cover_line_is_skipped():  # 사례집 — "2025" 가 제목이 되던 문제
    got = resolve_title(
        lines(("2025", None, True), ("경기도데이터분석 사례집", None, True), "효율적인개인하수처리시설 점검대상선정"),
        filename="01.(사례집)개인하수처리시설.pdf",
    )
    assert got == "경기도데이터분석 사례집"


def test_heading_group_ending_with_document_type_wins():  # 디에스아이 — 회사명 대신 보고서 제목
    got = resolve_title(
        lines(
            "에기협 제 23-대스-002", ("주식회사 디에스아이", None, True), "포항산단 스마트에너지 플랫폼 구축사업",
            ("에너지.온실가스감축 진단보고서", None, True), "2023. 08",
        ),
        filename="02 주식회사 디에스아이 진단요약서.pdf",
    )
    assert got == "에너지.온실가스감축 진단보고서"


def test_notice_number_line_is_not_the_title():  # 공고 hwpx — 제목 신호 없이 문단만 있는 경우
    got = resolve_title(
        lines(
            "[중소벤처기업부 공고 제2026-272호]",
            "2026년도 R&D성과확산 스마트공장 구축 지원사업 2차 공고",
            "『2026년도 R&D성과확산 스마트공장 구축 지원사업』의 지원계획을 다음과 같이 공고합니다.",
            "2026년 4월 17일",
        ),
        filename="「2026년도 R&D성과확산 스마트공장 구축 지원사업」2차 공고.hwpx",
    )
    assert got == "2026년도 R&D성과확산 스마트공장 구축 지원사업 2차 공고"


def test_consecutive_short_cover_lines_are_joined():  # UIUX 보고서 hwpx
    got = resolve_title(
        lines("범정부 UI/UX 디자인시스템 고도화 및 운영관리", "AI 기반 UI/UX 개선", "컨설팅 보고서", "2025년 12월"),
        filename="AI 기반 UIUX 개선 컨설팅 보고서_v1.0.hwpx",
    )
    assert got == "범정부 UI/UX 디자인시스템 고도화 및 운영관리 AI 기반 UI/UX 개선 컨설팅 보고서"


def test_largest_font_lines_form_the_title():  # 검수기준서 docx — 글자 크기 신호
    got = resolve_title(
        lines(
            ("AIDE", 10.0), ("AI 외주(디구루) Driver DNA™ Prototype", 16.0), ("성과물 검수 기준서", 21.0),
            ("Acceptance Criteria for Driver DNA™ Prototype", 9.5), ("행동 벡터 · 4유형 분석", 9.0),
        ),
        filename="AIDE_디구루_AI검수기준서_v1.3_고객사피드백반영.docx",
    )
    assert got == "AI 외주(디구루) Driver DNA™ Prototype 성과물 검수 기준서"


def test_same_size_title_lines_are_kept_together():  # AIDE 제안서 docx
    got = resolve_title(
        lines(
            ("AIDE", 16.0), ("AI 기반 사고 예방 플랫폼 구축 제안서", 16.0),
            ("CAN Data, ADAS, AI DashCAM-DMS, GPS 및 운행 데이터 통합 분석", 11.0), ("작성 기준일: 2026년 6월 22일", 10.0),
        ),
        filename="AIDE_AI플랫폼_구축제안서_v2.docx",
    )
    assert got == "AIDE AI 기반 사고 예방 플랫폼 구축 제안서"


# ---------------------------------------------------- 폴백과 OCR 오인식 보정
def test_chapter_heading_is_not_a_title_falls_back_to_filename():  # AX 사례 "2. AX 사례"
    got = resolve_title(
        [], filename="정형데이터 기반_AX사례_에너지 효율 및 수요 예측_20260211.pdf", fallback_heading="2. AX 사례",
    )
    assert got == "정형데이터 기반 AX사례 에너지 효율 및 수요 예측"


def test_missing_title_falls_back_to_filename():  # 공고 hwpx 가 NULL 이던 경우
    assert resolve_title([], filename="공고문_2026.hwpx") == "공고문 2026"


def test_ocr_damaged_title_is_replaced_by_the_similar_filename():  # 심야버스
    got = resolve_title(
        lines("넥데이터 기반 심아버스 노선 수립올 위한 분석"),
        filename="01_빅데이터 기반 심야버스 노선 수립을 위한 분석(요약본).pdf", ocr_used=True,
    )
    assert got == "빅데이터 기반 심야버스 노선 수립을 위한 분석(요약본)"


def test_ocr_noisy_multiline_cover_prefers_filename_when_similar():  # 서울 PDF
    got = resolve_title(
        lines("@ 골목길 특성 및 지역 낙인 Sue 고려한", "ㅣ 서울시 도시 범죄 취 약 지 분석 및", "억제 방안 연구", "정진도 서울대학교"),
        filename="[서울 데이터 펠로우십]서울시 도시 범죄 취약지 분석 및 억제 방안연구.pdf", ocr_used=True,
    )
    assert got == "서울시 도시 범죄 취약지 분석 및 억제 방안연구"


def test_ocr_title_unrelated_to_filename_is_kept():
    got = resolve_title(
        lines("완전히 다른 제목의 연구 보고서"), filename="scan_0001.pdf", ocr_used=True,
    )
    assert got == "완전히 다른 제목의 연구 보고서"


def test_nothing_available_returns_none():
    assert resolve_title([], filename="") is None


# ---- 재처리 후 실측에서 드러난 사례 ----
def test_chapter_heading_ending_with_doc_type_word_is_not_a_title():
    # HWPX UIUX 보고서: "1. 사업개요" 가 '개요' 어미 때문에 제목이 되던 문제
    got = resolve_title(
        lines("2025년 12월", "<차례>", "1. 사업개요", "1.1. 배경 및 목적"),
        filename="AI 기반 UIUX 개선 컨설팅 보고서_v1.0.hwpx",
        fallback_heading="1. 사업개요",
    )
    assert got == "AI 기반 UIUX 개선 컨설팅 보고서"


def test_roman_numeral_chapter_is_not_merged_into_heading_group():
    got = resolve_title(
        lines(("디지털 정부서비스 UI/UX 가이드라인", None, True), ("Ⅳ. 컴포넌트", None, True), ("아이덴티티", None, True)),
        filename="디지털 정부서비스 UIUX가이드라인 [240709].pdf",
    )
    assert got == "디지털 정부서비스 UI/UX 가이드라인"


def test_slide_bullet_line_is_not_a_title():
    got = resolve_title(
        [], filename="정형데이터 기반_AX사례_에너지 효율 및 수요 예측_20260211.pdf",
        fallback_heading="들어가기 앞서 (1/2) ⚫ 왜 Ai가 필요한가 :",
    )
    assert got == "정형데이터 기반 AX사례 에너지 효율 및 수요 예측"


def test_garbled_cover_close_to_filename_prefers_filename_even_without_ocr_flag():
    got = resolve_title(
        lines("넥데이터 기반 심아버스 노선 수립올 위한 분석"),
        filename="01_빅데이터 기반 심야버스 노선 수립을 위한 분석(요약본).pdf",
    )
    assert got == "빅데이터 기반 심야버스 노선 수립을 위한 분석(요약본)"
