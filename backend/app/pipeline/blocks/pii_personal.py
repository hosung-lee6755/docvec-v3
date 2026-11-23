"""문맥으로 찾는 개인정보(전체 점검 1-6, 2026-11-16): 이름, 주소, 운전면허, 여권, 사업자등록번호.

번호 모양만으로 정해지는 것(운전면허, 사업자등록번호)을 빼면 모두 앞뒤 문맥을 본다. 문서의 대부분은
공고문과 보고서라서, 기관 주소나 직함만 적힌 줄까지 가리면 "어디에 접수하느냐"에 답하지 못한다.
그래서 놓치는 쪽을 택한다. 사람에게 붙은 표지("성명: ", "주소: ")나 호칭("○○○ 과장")이 있을 때만 잡는다.

한계: 표의 머리글과 값이 다른 행에 있으면("| 성명 |" 아래 행의 이름) 표지를 잇지 못해 놓친다.
그런 문서는 사용자 사전의 PERSON 항목으로 보완한다.
"""
import re
from collections import Counter

Match = tuple[int, int, float]

_CONTEXT_WINDOW = 20
_ORG_CONTEXT_WINDOW = 40

# 통계청 성씨 분포의 위쪽(인구의 99% 이상)
_SURNAMES = frozenset(
    "김이박최정강조윤장임한오서신권황안송류전홍고문양손배백허유남심노하곽성차주우구민진지엄채원천방공"
    "현함변염여추도소석선설마길연위표명기반왕금옥육인맹제모탁국어은편용예봉경사부가복태목형두감"
)
# 성으로 시작하지만 이름이 아닌 말. 표지나 호칭 바로 옆에 자주 온다
_NOT_NAMES = frozenset({
    "변경", "연락처", "주소", "전화", "이메일", "소속", "직위", "직급", "부서", "성별", "서명", "날인", "기재",
    "작성", "입력", "확인", "없음", "미정", "공란", "해당", "전체", "기타", "명단", "정보", "관리", "등록",
    "표시", "지정", "선택", "설정", "주민", "성명", "이름", "신임", "전임", "현임", "후임", "선임", "수석",
    "전문", "고객", "우리", "이번", "지난", "기존", "모든", "여러", "선생", "사장", "회장", "원장", "국장",
    "차관", "장관", "의원", "위원", "기사", "여사", "손님", "주인", "주무", "성함", "연구", "지도", "주임",
    "이사", "전무", "상무", "부장", "차장", "과장", "대리", "사원", "조교", "강사", "이하", "이상", "한국",
    "전국", "지역", "기관", "기업", "공단", "제출", "신청", "접수", "서류", "양식", "별지", "별첨", "참고",
    "사용", "경우", "형식", "우측", "좌측", "이용", "가입", "지원", "신규", "정보", "현황", "명의", "인적",
    "지하",  # "지하주차장"을 "지하주 차장"으로 읽는다(기계설비 성능점검 보고서, 2026-11-21)
})
_NAME_LABEL_RE = re.compile(
    r"(?:성\s?명|이\s?름|성\s?함|대표자(?:명)?|담당자(?:명)?|신청인|신청자|작성자|책임자|보호자|수령인|예금주|참석자)"
    r"(\s*[:：|]\s*|\s+)([가-힣]{2,4})(?![가-힣])"
)
# 호칭만으로 찾을 때는 세 글자 이름만 본다. 두 글자와 네 글자는 "홍보 과장"처럼 부서 이름과 겹친다
_NAME_TITLE_RE = re.compile(
    r"(?<![가-힣])([가-힣]{3})\s?"
    r"(?:씨|님|과장|부장|차장|팀장|대리|주임|교수|박사|실장|센터장|주무관|사무관|연구관|선임연구원|책임연구원|수석연구원)"
    r"(?=$|[^가-힣]|[은는이가을를에의과와께도만])"
)
# 호칭 앞의 세 글자가 이런 글자로 끝나면 조직 이름이다("연구소 실장", "사업단 팀장")
_ORG_ENDINGS = frozenset("소단팀과부실회처청")
_PARTICLES = frozenset("은는이가을를에의과와께도만")
_LABEL_CONFIDENCE = 0.7
_TITLE_CONFIDENCE = 0.5
# 잡은 이름 1건당 표지 없이 다시 나와도 되는 자리 수. 예시 이름("홍길동")은 3건 잡혀 13번 다시 나왔고,
# 이름으로 잘못 잡힌 일반 낱말("기계설비")은 1건 잡혀 929번 다시 나왔다(2026-11-21 전체 문서 측정)
_MAX_REPEATS_PER_DETECTION = 20

_REGION = (
    r"(?:서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주"
    r"|충청북도|충청남도|전라북도|전라남도|경상북도|경상남도)"
    r"(?:특별자치시|특별자치도|특별시|광역시|시|도)?"
)
_DISTRICTS = r"(?:[가-힣0-9]+(?:시|군|구)\s+){0,2}"
_ROAD = r"[가-힣0-9·.]+(?:로|길)\s?\d+(?:-\d+)?(?:번길\s?\d+(?:-\d+)?)?"
_LOT = r"[가-힣0-9]+(?:동|리|가)\s+(?:산\s?)?\d+(?:-\d+)?(?:번지)?"
_DETAIL = r"(?:[ ,]+\d+동)?(?:[ ,]+\d+층)?(?:[ ,]+\d+호)?"
_ADDRESS_RE = re.compile(
    rf"{_REGION}\s+{_DISTRICTS}(?:[가-힣0-9]+(?:읍|면|동)\s+)?(?:{_ROAD}|{_LOT}){_DETAIL}"
)
_PERSONAL_ADDRESS_RE = re.compile(r"(?:주\s?소|거주지|자택|주민등록지|배송지|수령지|본적)[^\n]{0,8}$")
# 기관의 주소는 공개된 정보다. 접수처와 소재지를 가리면 공고문에서 답을 찾지 못한다
_ORG_ADDRESS_RE = re.compile(
    r"소재지|사업장|본사|본점|지점|접수처|제출처|방문|우편|오시는|찾아오|센터|진흥원|재단|공단|협회|공사|본부"
    r"|청사|회사|법인|기관|학교|병원|사무소|사무실"
)
_ADDRESS_CONFIDENCE = 0.6

_DRIVER_LICENSE_RE = re.compile(r"(?<![\d-])\d{2}-\d{2}-\d{6}-\d{2}(?![\d-])")
_PASSPORT_RE = re.compile(r"(?<![A-Za-z0-9])(?:[MSRODG]\d{8}|[MSRODG]\d{3}[A-Z]\d{4})(?![A-Za-z0-9])")
_PASSPORT_CONTEXT_RE = re.compile(r"여권|passport|Passport|PASSPORT")
_BIZNO_RE = re.compile(r"(?<![\d-])(\d{3})-(\d{2})-(\d{5})(?![\d-])")
_BIZNO_WEIGHTS = (1, 3, 7, 1, 3, 7, 1, 3, 5)


def _before(text: str, start: int, window: int = _CONTEXT_WINDOW) -> str:
    return text[max(0, start - window):start]


def is_plausible_name(candidate: str) -> bool:
    return candidate[0] in _SURNAMES and not any(candidate.startswith(word) for word in _NOT_NAMES)


def _label_name(candidate: str, has_delimiter: bool) -> str | None:
    """표지 뒤의 글자에서 이름만 남긴다. "홍길동은"처럼 조사가 붙어 네 글자가 된 것은 조사를 뗀다.
    표지와 이름 사이에 쌍점이나 표의 칸막이 없이 빈칸만 있으면 문장 속의 말일 수 있다
    ("이름 형식에", "신청인 경우"). 그때는 조사로 끝나지 않는 세 글자만 이름으로 본다."""
    if not is_plausible_name(candidate):
        return None
    name = candidate[:3] if len(candidate) == 4 and candidate[-1] in _PARTICLES else candidate
    if not has_delimiter and (len(name) != 3 or name[-1] in _PARTICLES):
        return None
    return name


_GENERIC_NAME_LABEL_RE = re.compile(r"이\s?름")
# 사람이나 역할을 가리키는 낱말의 끝(담당자, 신청인, 직원, 팀장, 고객님, 학생, 고객, 예금주)
_PERSON_WORD_ENDINGS = ("자", "인", "원", "장", "님", "생", "객", "주", "씨")


def _is_name_of_something(text: str, match: re.Match) -> bool:
    """"유형 이름", "화면 이름", "코드와 이름"처럼 앞 낱말에 붙은 "이름"은 사람 이름 표지가 아니다. 사람 이름
    표지는 칸이나 줄의 맨 앞에 온다("| 이름 | 홍길동", "이름: 홍길동"). 표의 머리글에서 다음 칸을 이름으로
    잡아 "유형별", "이벤트" 같은 말을 가리던 문제(고도화·완료보고서 실측, 2026-11-19)."""
    label_end = match.start(1)
    label = text[match.start():label_end]
    if not _GENERIC_NAME_LABEL_RE.fullmatch(label):
        return False
    before = text[:match.start()].rstrip(" \t")
    if not before or not ("가" <= before[-1] <= "힣"):
        return False
    # "담당자 이름: 홍길동", "신청인 이름"처럼 앞 낱말이 사람을 가리키면 사람 이름 표지다(미탐이 오탐보다 위험)
    return not before.endswith(_PERSON_WORD_ENDINGS)


def name_matches(text: str) -> list[Match]:
    """표지("성명: 홍길동")나 호칭("홍길동 과장") 옆의 이름. 표지 쪽을 더 믿는다."""
    found: dict[int, tuple[int, float]] = {}
    position = 0
    while (match := _NAME_LABEL_RE.search(text, position)) is not None:
        name = None if _is_name_of_something(text, match) else _label_name(
            match.group(2), has_delimiter=bool(match.group(1).strip())
        )
        if name:
            found[match.start(2)] = (match.start(2) + len(name), _LABEL_CONFIDENCE)
            position = match.end()
        else:
            # "담당자 이름: 홍길동"처럼 표지 뒤가 또 표지면 그 표지부터 다시 찾는다
            position = match.start() + 1
    for match in _NAME_TITLE_RE.finditer(text):
        candidate = match.group(1)
        if match.start(1) not in found and is_plausible_name(candidate) and candidate[-1] not in _ORG_ENDINGS:
            found[match.start(1)] = (match.end(1), _TITLE_CONFIDENCE)
    return [(start, end, confidence) for start, (end, confidence) in sorted(found.items())]


def repeated_name_matches(text: str, matches: list[Match]) -> list[Match]:
    """이미 이름으로 잡은 값이 표지 없이 다시 나온 자리. 표 칸("| 홍길동 / 대표 |")처럼 표지와 떨어진 곳이다.

    낱말 속에 든 경우("정민수산")까지 번지지 않도록 앞은 한글이 아니고, 뒤는 한글이 아니거나 조사 한 글자여야 한다.
    탐지 1건당 다시 나온 자리가 너무 많으면 그 값은 번지지 않는다("| 담당자 | 기계설비 |"의 "기계설비"가 930곳)."""
    names = {text[start:end]: confidence for start, end, confidence in matches}
    detected = Counter(text[start:end] for start, end, _ in matches)
    taken = {start for start, _, _ in matches}
    out: list[Match] = []
    for name, confidence in names.items():
        repeats = [
            match.span() for match in re.finditer(re.escape(name), text)
            if match.start() not in taken and not _is_hangul_at(text, match.start() - 1) and _ends_word(text, match.end())
        ]
        # 문서에서 너무 자주 나오는 값은 사람 이름이 아니라 그 문서의 일반 낱말이다
        if len(repeats) > _MAX_REPEATS_PER_DETECTION * detected[name]:
            continue
        out.extend((start, end, confidence) for start, end in repeats)
    return sorted(out)


def _is_hangul_at(text: str, index: int) -> bool:
    return 0 <= index < len(text) and "가" <= text[index] <= "힣"


def _ends_word(text: str, end: int) -> bool:
    if not _is_hangul_at(text, end):
        return True
    return text[end] in _PARTICLES and not _is_hangul_at(text, end + 1)


def address_matches(text: str) -> list[Match]:
    """사람의 주소. 바로 앞에 "주소" 같은 표지가 있고, 그 앞뒤에 기관을 가리키는 말이 없어야 한다."""
    out = []
    for match in _ADDRESS_RE.finditer(text):
        if not _PERSONAL_ADDRESS_RE.search(_before(text, match.start())):
            continue
        if _ORG_ADDRESS_RE.search(_before(text, match.start(), _ORG_CONTEXT_WINDOW)):
            continue
        out.append((match.start(), match.end(), _ADDRESS_CONFIDENCE))
    return out


def driver_license_matches(text: str) -> list[Match]:
    return [(m.start(), m.end(), 0.9) for m in _DRIVER_LICENSE_RE.finditer(text)]


def passport_matches(text: str) -> list[Match]:
    return [
        (m.start(), m.end(), 0.85) for m in _PASSPORT_RE.finditer(text)
        if _PASSPORT_CONTEXT_RE.search(_before(text, m.start(), _ORG_CONTEXT_WINDOW))
    ]


def bizno_checksum_valid(digits: str) -> bool:
    if len(digits) != 10 or not digits.isdigit():
        return False
    values = [int(d) for d in digits]
    total = sum(v * w for v, w in zip(values[:9], _BIZNO_WEIGHTS)) + values[8] * 5 // 10
    return (10 - total % 10) % 10 == values[9]


def bizno_matches(text: str) -> list[Match]:
    return [
        (m.start(), m.end(), 0.9) for m in _BIZNO_RE.finditer(text)
        if bizno_checksum_valid("".join(m.groups()))
    ]


DETECTORS = {
    "ADDRESS": address_matches,
    "DRIVER_LICENSE": driver_license_matches,
    "PASSPORT": passport_matches,
    "BIZNO": bizno_matches,
}
