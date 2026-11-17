"""문맥으로 찾는 개인정보(전체 점검 1-6): 이름, 주소, 운전면허, 여권, 사업자등록번호."""
import pytest

from app.pipeline.blocks import pii_blocks as pb
from app.pipeline.blocks import pii_personal as pp


def _found(matches, text):
    return [text[start:end] for start, end, _ in matches]


@pytest.mark.parametrize("text, names", [
    ("성명: 홍길동", ["홍길동"]),
    ("| 성 명 | 김영희 | 소속 | 총무팀 |", ["김영희"]),
    ("담당자 박철수 (내선 123)", ["박철수"]),
    ("대표자명：남궁민수", ["남궁민수"]),
    ("문의는 이수진 과장에게 한다", ["이수진"]),
    ("최민호님과 정다은 씨가 참석했다", ["최민호", "정다은"]),
    ("담당자 홍길동은 부재중이다", ["홍길동"]),
])
def test_names_next_to_labels_and_titles_are_found(text, names):
    assert _found(pp.name_matches(text), text) == names


@pytest.mark.parametrize("text", [
    "파일 이름 변경 방법",            # 성으로 시작하지만 이름이 아닌 말
    "담당자 연락처는 아래와 같다",
    "신임 팀장이 부임했다",
    "고객님께 안내드립니다",
    "해당 부장이 결재한다",            # 성이 아닌 글자로 시작
    "성명 및 소속을 적는다",
    "홍길동은 서울에 산다",            # 표지도 호칭도 없다
    "이름 형식에 맞게 적고 신청인 경우 우측에 서명한다",   # 빈칸만 사이에 둔 문장 속의 말
    "성명 사용자 구분",
    "선생님과 위원님께 드립니다",
    "홍보 과장과 연구소 실장, 사업단 팀장이 모였다",   # 부서와 조직 이름
])
def test_words_that_only_look_like_names_are_left_alone(text):
    assert pp.name_matches(text) == []


def test_label_names_score_higher_than_title_names_and_are_not_doubled():
    text = "성명: 홍길동 과장"

    assert pp.name_matches(text) == [(4, 7, 0.7)]


@pytest.mark.parametrize("text, address", [
    ("주소: 서울특별시 강남구 테헤란로 123, 5층 502호", "서울특별시 강남구 테헤란로 123, 5층 502호"),
    ("거주지 경기도 성남시 분당구 판교역로 235", "경기도 성남시 분당구 판교역로 235"),
    ("자택 주소 | 부산 해운대구 우동 1408-2번지", "부산 해운대구 우동 1408-2번지"),
    ("배송지: 세종 한누리대로 2130", "세종 한누리대로 2130"),
])
def test_personal_addresses_are_found(text, address):
    assert _found(pp.address_matches(text), text) == [address]


@pytest.mark.parametrize("text", [
    "접수처: 서울특별시 강남구 테헤란로 123",                    # 표지가 사람의 주소가 아니다
    "진흥원 주소: 대전광역시 유성구 가정로 218",                 # 기관의 주소
    "사업장 소재지 주소 경기도 수원시 영통구 삼성로 129",
    "서울특별시 강남구 테헤란로 123에서 행사를 연다",            # 표지 없음
    "주소: 미정",
])
def test_organisation_and_unlabelled_addresses_are_left_alone(text):
    assert pp.address_matches(text) == []


def test_driver_license_and_passport():
    text = "면허 11-22-333333-44, 여권번호 M12345678, 신여권 M123A4567, 모델 S12345678"

    assert _found(pp.driver_license_matches(text), text) == ["11-22-333333-44"]
    assert _found(pp.passport_matches(text), text) == ["M12345678", "M123A4567", "S12345678"]
    assert pp.passport_matches("부품 번호 M12345678") == []
    assert pp.driver_license_matches("2026-11-123456-78-9") == []


def test_business_number_needs_a_valid_checksum():
    assert pp.bizno_checksum_valid("1248100998") and not pp.bizno_checksum_valid("1248100999")
    text = "사업자등록번호 124-81-00998, 관리번호 123-45-67890"

    assert _found(pp.bizno_matches(text), text) == ["124-81-00998"]


def test_block_defaults_include_new_types_but_not_business_numbers():
    assert {"ADDRESS", "DRIVER_LICENSE", "PASSPORT", "NAME"} <= set(pb._ALL_ENTITY_TYPES)
    assert "BIZNO" not in pb._ALL_ENTITY_TYPES and "BIZNO" in pb._ENTITY_PRIORITY
    assert set(pb._ALL_ENTITY_TYPES) <= set(pb._ENTITY_PRIORITY)
    assert pb.PiiDetectBlock().block_version == "1.1.0"


def test_block_regex_dispatch_reaches_the_new_detectors():
    text = "면허 11-22-333333-44 주소: 서울특별시 강남구 테헤란로 123"

    assert [text[s:e] for s, e, _ in pb._detect_regex_matches(text, "DRIVER_LICENSE")] == ["11-22-333333-44"]
    assert len(pb._detect_regex_matches(text, "ADDRESS")) == 1
    assert pb._detect_regex_matches(text, "UNKNOWN") == []
    # 운전면허가 계좌보다 먼저 자리를 차지한다(계좌 모양과 겹친다)
    assert pb._ENTITY_PRIORITY.index("DRIVER_LICENSE") < pb._ENTITY_PRIORITY.index("ACCOUNT")
