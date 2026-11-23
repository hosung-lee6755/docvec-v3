"""민감정보 탐지 블록 — 통합 설계서 §3.3⑩.

1차 정규식 엔진(주민번호/전화/이메일/계좌/카드) + 체크섬(주민번호/카드) +
사용자 사전 PERSON 타입 매칭(이름).

2026-11-16(전체 점검 1-6): 문맥으로 찾는 이름(표지·호칭), 주소, 운전면허, 여권을 더했다
(pii_personal.py). 사업자등록번호(BIZNO)는 법인의 공개 정보인 경우가 많아 기본 탐지에서 빼고,
설정에서 골랐을 때만 찾는다. NER(로컬 LLM 보조)은 여전히 별도 작업이다.
"""
import re
from dataclasses import dataclass

from pydantic import BaseModel

from app.pipeline.blocks.base import BaseBlock, BlockContext, BlockResult
from app.pipeline.blocks import pii_personal
from app.pipeline.blocks.content_blocks import _carry, _upstream_text
from app.pipeline.blocks.normalization_blocks import (
    _dictionary_version_cutoff,
    _find_spans,
    _load_entries_as_of,
)

_RRN_RE = re.compile(r"(?<!\d)(\d{6})-?([1-4]\d{6})(?!\d)")
_PHONE_RE = re.compile(r"(?<!\d)(01[0-9]-?\d{3,4}-?\d{4}|0\d{1,2}-\d{3,4}-\d{4})(?!\d)")
# 국제 표기(+82 10-…, +82 (0)10-…)와 띄어 쓴 표기(010 1234 5678, 010 - 1234 - 5678)의 휴대전화.
# 같은 형식의 유선번호("053) 256-4413", "+82-33-811-2001")와 해외 번호는 실제 문서에서 모두
# 기관 연락처였으므로 넓히지 않는다(2026-11-23 전체 문서 조사)
_MOBILE_EXTRA_RE = re.compile(
    r"(?<![\d+])(?:\+82[\s-]*\)?[\s-]*(?:\(0\)\s*)?1[016789]|01[016789])"
    r"(?:\s*-\s*|\s)\d{3,4}(?:\s*-\s*|\s)\d{4}(?!\d)"
)
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# 체크섬 없는 패턴 — 은행 계좌번호는 은행별 자릿수/구분이 제각각이라 오탐
# 가능성이 있음을 감안해 낮은 confidence를 부여한다.
_ACCOUNT_RE = re.compile(r"(?<!\d)\d{2,6}-\d{2,6}-\d{2,8}(?!\d)")
_CARD_RE = re.compile(r"(?<!\d)\d{4}-?\d{4}-?\d{4}-?\d{4}(?!\d)")

_RRN_WEIGHTS = [2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5]

# 공고문·보고서에서 실제로 나온 오탐을 줄이는 문맥 규칙(2026-11-13 전처리 검토).
# 계좌번호 패턴은 날짜(2026-06-08), 사업자등록번호, 한전 고객번호, 문서번호에도 맞는다. 일정이 가려져
# "언제 접수하느냐"에 답하지 못했다. 그래서 바로 앞에 계좌·은행 단서가 있을 때만 계좌로 본다.
_CONTEXT_WINDOW = 20
_ACCOUNT_CONTEXT_RE = re.compile(
    r"계좌|은행|예금|입금|송금|이체|뱅크|농협|우체국|새마을금고|신협|수협|증권"
    # 은행 이름 가운데 일반 단어로도 흔한 것(국민, 기업, 우리, 하나, 지역명)은 사업자번호 오탐을 부르므로 뺀다
    r"|신한|카카오|토스|씨티|SC제일"
)
# 계좌 단서 뒤에 "A, B", "A 또는 B"처럼 이어 적은 계좌는 앞 계좌의 단서를 이어받는다
_ACCOUNT_LIST_GAP_RE = re.compile(r"[ \t,/·]*(?:및|또는|or)?[ \t,/·]*")
_DATE_LIKE_RE = re.compile(r"(?:19|20)\d{2}-(?:0?[1-9]|1[0-2])-(?:0?[1-9]|[12]\d|3[01])")
# 공고문의 기관 문의처(유선)는 공개된 업무 연락처다. 번호 바로 앞(같은 줄 12자 이내)에 문의·대표 같은
# 말이 있을 때만 뺀다. 휴대전화는 어떤 문맥이어도 개인정보로 본다
_PUBLIC_CONTACT_RE = re.compile(r"(?:문의|대표|고객센터|콜센터|상담|안내|접수|TEL|Tel|tel|☎|FAX|Fax|팩스)[^\n]{0,12}$")
# 공고문 표의 "국가뿌리산업진흥센터 032-…", "임치센터(02-…, …@….or.kr)"처럼 기관명 바로 뒤의 유선번호와
# 공공기관 도메인 메일은 기관 연락처다. 사람 직함과 겹치는 "연구원"은 넣지 않는다(2026-11-13 재처리 검증)
_ORG_CONTACT_RE = re.compile(
    r"(?:센터|진흥원|재단|공단|협회|협력단|진흥회|조합|공사|본부)\s*[(|:,]?\s*(?:[^\n]{0,24},\s*)?$"
)
# 고객번호·등록번호처럼 이름이 붙은 식별번호는 전화번호 모양이어도 전화번호가 아니다
_ID_NUMBER_CONTEXT_RE = re.compile(r"(?:고객번호|관리번호|등록번호|접수번호|문서번호|사업자번호)[^\n]{0,6}$")
# 공공기관 도메인 메일은 바로 앞에 접수·문의 같은 창구 표시가 있을 때만 공고문의 업무 메일로 본다.
# 담당자·연구원처럼 사람에게 붙은 주소는 공공기관 도메인이어도 개인정보다(2026-11-13 리뷰)
_PUBLIC_EMAIL_SUFFIXES = (".go.kr", ".or.kr", ".re.kr")
_PUBLIC_EMAIL_CONTEXT_RE = re.compile(
    r"(?:문의|접수|제출|안내|고객센터|이메일|전자우편|E-?mail|e-?mail|EMAIL|메일)[^\n]{0,8}$"
)


def _preceding(text: str, start: int) -> str:
    return text[max(0, start - _CONTEXT_WINDOW):start]


def _is_account(text: str, match: re.Match, previous_account_end: int | None = None) -> bool:
    if _DATE_LIKE_RE.fullmatch(match.group()):
        return False
    if previous_account_end is not None and _ACCOUNT_LIST_GAP_RE.fullmatch(
        text, previous_account_end, match.start()
    ):
        return True
    return bool(_ACCOUNT_CONTEXT_RE.search(_preceding(text, match.start())))


def _account_matches(text: str) -> list[tuple[int, int, float]]:
    out: list[tuple[int, int, float]] = []
    previous_end = None
    for m in _ACCOUNT_RE.finditer(text):
        if _is_account(text, m, previous_end):
            out.append((m.start(), m.end(), 0.5))
            previous_end = m.end()
    return out


def _is_personal_phone(text: str, match: re.Match) -> bool:
    before = _preceding(text, match.start())
    if _ID_NUMBER_CONTEXT_RE.search(before):
        return False  # 고객번호·등록번호 같은 식별번호는 전화번호가 아니다
    if match.group().startswith("01"):
        return True
    return not (_PUBLIC_CONTACT_RE.search(before) or _ORG_CONTACT_RE.search(before))


def _phone_matches(text: str) -> list[tuple[int, int, float]]:
    found = [(m.start(), m.end(), 0.9) for m in _PHONE_RE.finditer(text) if _is_personal_phone(text, m)]
    for m in _MOBILE_EXTRA_RE.finditer(text):
        overlaps = any(start < m.end() and m.start() < end for start, end, _ in found)
        if not overlaps and not _ID_NUMBER_CONTEXT_RE.search(_preceding(text, m.start())):
            found.append((m.start(), m.end(), 0.9))
    return sorted(found)


def _is_personal_email(text: str, match: re.Match) -> bool:
    if not match.group().lower().endswith(_PUBLIC_EMAIL_SUFFIXES):
        return True
    before = _preceding(text, match.start())
    return not (_PUBLIC_EMAIL_CONTEXT_RE.search(before) or _ORG_CONTACT_RE.search(before))

# 우선순위 순서로 겹치는 매치를 먼저 차지한 쪽이 이긴다(예: 카드번호 패턴이
# 계좌번호 패턴과 겹치면 카드로 판정) — 이후 낮은 우선순위 탐지기는 이미
# 차지된 구간을 건너뛴다.
_ENTITY_PRIORITY = [
    "RRN", "CARD", "DRIVER_LICENSE", "BIZNO", "PHONE", "ACCOUNT", "EMAIL", "PASSPORT", "ADDRESS", "NAME",
]
# entity_types를 비웠을 때 찾는 유형. BIZNO는 골랐을 때만 찾는다
_ALL_ENTITY_TYPES = ["RRN", "PHONE", "EMAIL", "ACCOUNT", "CARD", "NAME", "ADDRESS", "DRIVER_LICENSE", "PASSPORT"]

_ACTION_TO_ENUM = {
    "mark_only": "MARK", "mask": "MASK", "tokenize": "TOKENIZE",
    "remove": "REMOVE", "exclude_from_embedding": "EXCLUDE_EMBEDDING",
}


def _rrn_checksum_valid(digits13: str) -> bool:
    if len(digits13) != 13 or not digits13.isdigit():
        return False
    total = sum(int(d) * w for d, w in zip(digits13[:12], _RRN_WEIGHTS))
    return (11 - (total % 11)) % 10 == int(digits13[12])


def _luhn_valid(digits: str) -> bool:
    if not digits.isdigit():
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _detect_regex_matches(text: str, entity_type: str) -> list[tuple[int, int, float]]:
    if entity_type == "RRN":
        out = []
        for m in _RRN_RE.finditer(text):
            if _rrn_checksum_valid(m.group(1) + m.group(2)):
                out.append((m.start(), m.end(), 0.95))
        return out
    if entity_type == "CARD":
        out = []
        for m in _CARD_RE.finditer(text):
            if _luhn_valid(re.sub(r"-", "", m.group())):
                out.append((m.start(), m.end(), 0.95))
        return out
    if entity_type == "PHONE":
        return _phone_matches(text)
    if entity_type == "ACCOUNT":
        return _account_matches(text)
    if entity_type == "EMAIL":
        return [(m.start(), m.end(), 0.98) for m in _EMAIL_RE.finditer(text) if _is_personal_email(text, m)]
    detector = pii_personal.DETECTORS.get(entity_type)
    return detector(text) if detector else []


_REGEX_ENTITY_TYPES = ("RRN", "CARD", "PHONE", "ACCOUNT", "EMAIL")


def mask_pii_patterns(text: str, mask_char: str = "*") -> str:
    """정규식으로 찾을 수 있는 개인정보(주민번호, 카드, 전화, 계좌, 이메일)를 같은 길이로 가린다.
    길이를 지키므로 위치(오프셋)는 그대로다. 이름(NAME)은 사전 기반이라 여기서 가리지 않는다."""
    chars = list(text)
    for entity_type in _REGEX_ENTITY_TYPES:
        for start, end, _confidence in _detect_regex_matches(text, entity_type):
            chars[start:end] = mask_char * (end - start)
    return "".join(chars)


@dataclass(frozen=True)
class PiiDecision:
    rejected: bool
    approved_by: object
    approved_at: object


def _previous_decisions(db, document_id, run_id) -> dict[tuple[str, str], PiiDecision]:
    """같은 문서의 가장 최근 실행 가운데 사람이 승인·해제한 탐지가 있는 실행의 결정. (유형, 원문) → 결정.
    재처리하면 탐지를 새로 만들어 결정이 사라지고, 해제(오탐 처리)한 값도 다시 가려졌다(2026-11-20 감사).
    같은 값에 승인과 해제가 섞여 있으면 가리는 쪽(승인)을 따른다."""
    from sqlalchemy import or_, select

    from app.core import crypto
    from app.db.models.pii_detection import PiiDetection

    decided = or_(PiiDetection.rejected.is_(True), PiiDetection.approved_at.isnot(None))
    source_run = db.scalar(
        select(PiiDetection.run_id)
        .where(PiiDetection.document_id == document_id, PiiDetection.run_id != run_id, decided)
        .order_by(PiiDetection.created_at.desc()).limit(1)
    )
    if source_run is None:
        return {}
    decisions: dict[tuple[str, str], PiiDecision] = {}
    for row in db.scalars(select(PiiDetection).where(PiiDetection.run_id == source_run, decided)).all():
        try:
            original = crypto.decrypt_secret(row.original_encrypted)
        except Exception:  # noqa: BLE001 — 복호화 못 하는 옛 행은 결정을 옮기지 않는다
            continue
        key = (row.entity_type, original)
        decision = PiiDecision(rejected=bool(row.rejected), approved_by=row.approved_by, approved_at=row.approved_at)
        previous = decisions.get(key)
        if previous is None or (previous.rejected and not decision.rejected):
            decisions[key] = decision
    return decisions


class PiiDetectConfig(BaseModel):
    entity_types: list[str] | None = None  # None = _ALL_ENTITY_TYPES(사업자등록번호 BIZNO는 골라야 찾는다)
    action: str = "mask"  # mark_only | mask | tokenize | remove | exclude_from_embedding
    mask_char: str = "*"
    require_admin_approval: bool = False


def _page_locator(db, document_id: str, text: str):
    """탐지 위치(정제·치환 뒤 글 기준)를 원문 쪽 번호로 바꾸는 함수. 청크와 같은 방법을 쓴다(storage_blocks).
    쪽 정보가 없는 문서(HWP, DOCX 등)는 None 을 돌려준다."""
    from app.db.models.document import Document
    from app.pipeline.page_alignment import PageLocator

    doc = db.get(Document, document_id)
    page_map = getattr(doc, "page_map", None)
    if not page_map:
        return lambda _offset: None
    return PageLocator(getattr(doc, "parsed_text", None) or "", page_map, text).page_for


class PiiDetectBlock(BaseBlock):
    @property
    def block_type(self) -> str:
        return "pii_detect"

    @property
    def category(self) -> str:
        return "구조·보호"

    @property
    def block_version(self) -> str:
        # 1.1.0 — 문맥 기반 이름, 주소, 운전면허, 여권, 사업자등록번호(선택) 탐지
        # 1.2.0 — "유형 이름"처럼 앞 낱말에 붙은 "이름"은 사람 이름 표지로 보지 않는다(2026-11-19)
        # 1.2.1 — 앞 낱말이 사람을 가리키면("담당자 이름") 표지로 보고, 겹친 표지("담당자 이름: …")도 찾는다
        # 1.3.0 — 같은 문서의 이전 승인·해제 결정을 이어받고, 해제한 값은 가리지 않는다(2026-11-20 감사)
        # 1.4.0 — 잡은 이름이 표지 없이 다시 나온 자리도 가리고, "지하주차장"을 이름으로 읽지 않는다(2026-11-21 감사)
        # 1.4.1 — 탐지 1건당 20번 넘게 다시 나오는 값은 일반 낱말로 보고 번지지 않는다(기계설비 매뉴얼 "기계설비" 930곳)
        # 1.4.2 — 탐지마다 원문 쪽 번호를 남긴다(민감정보 탭 "위치"가 모든 문서에서 비어 있었다, 2026-11-21)
        # 1.4.3 — 국제 표기(+82 10-…)와 띄어 쓴 휴대전화도 찾는다(2026-11-23)
        return "1.4.3"

    @property
    def config_schema(self):
        return PiiDetectConfig

    def run(self, context: BlockContext) -> BlockResult:
        from app.core import crypto
        from app.db.models.pii_detection import PiiDetection
        from app.db.models.workflow_run import WorkflowRun
        from app.db.session import get_sync_db

        if not context.document_id:
            raise ValueError("실행할 문서가 지정되지 않았습니다.")
        cfg = PiiDetectConfig(**(context.config or {}))
        upstream = _carry(context)
        text = _upstream_text(context)
        entity_types = set(cfg.entity_types or _ALL_ENTITY_TYPES)

        db = get_sync_db()
        try:
            run = db.get(WorkflowRun, context.run_id)
            claimed: list[tuple[int, int]] = []
            found: list[tuple[int, int, str, float]] = []

            for entity_type in _ENTITY_PRIORITY:
                if entity_type not in entity_types:
                    continue
                if entity_type == "NAME":
                    cutoff = _dictionary_version_cutoff(db, run.dictionary_version if run else None)
                    entries = _load_entries_as_of(db, "custom_word", cutoff)
                    matches = []
                    for entry in entries:
                        if entry.term_type != "PERSON":
                            continue
                        matches.extend(
                            (s, e, 0.6) for s, e in _find_spans(entry.term, "EXACT", entry.case_sensitive, text)
                        )
                        for variant in entry.variants:
                            matches.extend(
                                (s, e, 0.6)
                                for s, e in _find_spans(variant.variant_term, "EXACT", entry.case_sensitive, text)
                            )
                    # 사전에 없는 이름은 표지와 호칭으로 찾는다. 겹치면 먼저 넣은 사전 쪽이 이긴다
                    matches.extend(pii_personal.name_matches(text))
                    # 잡은 이름이 표지 없이 다시 나온 자리(표 칸 등)도 같은 이름으로 가린다
                    matches.extend(pii_personal.repeated_name_matches(text, matches))
                else:
                    matches = _detect_regex_matches(text, entity_type)

                for start, end, confidence in matches:
                    if any(start < ce and cs < end for cs, ce in claimed):
                        continue
                    claimed.append((start, end))
                    found.append((start, end, entity_type, confidence))

            excluded_spans: list[list[int]] = []
            new_text = text
            action_enum = _ACTION_TO_ENUM[cfg.action]
            decisions = _previous_decisions(db, context.document_id, context.run_id) if found else {}
            page_for = _page_locator(db, context.document_id, text) if found else (lambda _offset: None)
            undecided = 0

            for start, end, entity_type, confidence in sorted(found, key=lambda f: f[0], reverse=True):
                original = text[start:end]
                decision = decisions.get((entity_type, original))
                rejected = bool(decision and decision.rejected)
                undecided += decision is None
                masked = None
                if cfg.action == "mask":
                    masked = cfg.mask_char * len(original)
                elif cfg.action == "tokenize":
                    masked = f"[MASK:{entity_type}]"
                elif cfg.action == "remove":
                    masked = ""
                # 해제(오탐 처리)한 값은 글에 그대로 둔다. 탐지 기록은 '해제됨'으로 남겨 탭에서 다시 고를 수 있다
                if masked is not None and not rejected:
                    new_text = new_text[:start] + masked + new_text[end:]
                if cfg.action == "exclude_from_embedding" and not rejected:
                    excluded_spans.append([start, end])

                db.add(PiiDetection(
                    run_id=context.run_id, document_id=context.document_id,
                    entity_type=entity_type, action=action_enum,
                    original_encrypted=crypto.encrypt_secret(original),
                    masked_value=masked,
                    confidence=confidence, start_offset=start, end_offset=end,
                    page_number=page_for(start),
                    rejected=rejected,
                    approved_by=decision.approved_by if decision and not rejected else None,
                    approved_at=decision.approved_at if decision and not rejected else None,
                ))
            db.commit()

            output = {**upstream, "text": new_text}
            if excluded_spans:
                merged = [list(s) for s in (upstream.get("pii_excluded_spans") or [])]
                merged.extend(excluded_spans)
                output["pii_excluded_spans"] = merged

            return BlockResult(
                output=output,
                metrics={"pii_detections": len(found)},
                # 모두 이전 실행에서 사람이 정한 값이면 다시 검토를 기다리지 않는다
                requires_review=cfg.require_admin_approval and undecided > 0,
            )
        finally:
            db.close()
