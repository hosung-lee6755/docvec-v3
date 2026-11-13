"""민감정보 탐지 블록 — 통합 설계서 §3.3⑩.

1차 정규식 엔진(주민번호/전화/이메일/계좌/카드) + 체크섬(주민번호/카드) +
사용자 사전 PERSON 타입 매칭(이름)까지만 구현한다. 주소(ADDRESS)는
DictionaryEntry.term_type에 대응 값이 없고 신뢰할 정규식도 없어 제외,
NER(로컬 LLM 보조)도 별도 작업으로 미룬다(둘 다 §13 Task 5 축소 범위).
"""
import re

from pydantic import BaseModel

from app.pipeline.blocks.base import BaseBlock, BlockContext, BlockResult
from app.pipeline.blocks.content_blocks import _carry, _upstream_text
from app.pipeline.blocks.normalization_blocks import (
    _dictionary_version_cutoff,
    _find_spans,
    _load_entries_as_of,
)

_RRN_RE = re.compile(r"(?<!\d)(\d{6})-?([1-4]\d{6})(?!\d)")
_PHONE_RE = re.compile(r"(?<!\d)(01[0-9]-?\d{3,4}-?\d{4}|0\d{1,2}-\d{3,4}-\d{4})(?!\d)")
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


def _is_personal_email(text: str, match: re.Match) -> bool:
    if not match.group().lower().endswith(_PUBLIC_EMAIL_SUFFIXES):
        return True
    before = _preceding(text, match.start())
    return not (_PUBLIC_EMAIL_CONTEXT_RE.search(before) or _ORG_CONTACT_RE.search(before))

# 우선순위 순서로 겹치는 매치를 먼저 차지한 쪽이 이긴다(예: 카드번호 패턴이
# 계좌번호 패턴과 겹치면 카드로 판정) — 이후 낮은 우선순위 탐지기는 이미
# 차지된 구간을 건너뛴다.
_ENTITY_PRIORITY = ["RRN", "CARD", "PHONE", "ACCOUNT", "EMAIL", "NAME"]
_ALL_ENTITY_TYPES = ["RRN", "PHONE", "EMAIL", "ACCOUNT", "CARD", "NAME"]

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
        return [(m.start(), m.end(), 0.9) for m in _PHONE_RE.finditer(text) if _is_personal_phone(text, m)]
    if entity_type == "ACCOUNT":
        return _account_matches(text)
    if entity_type == "EMAIL":
        return [(m.start(), m.end(), 0.98) for m in _EMAIL_RE.finditer(text) if _is_personal_email(text, m)]
    return []


_REGEX_ENTITY_TYPES = ("RRN", "CARD", "PHONE", "ACCOUNT", "EMAIL")


def mask_pii_patterns(text: str, mask_char: str = "*") -> str:
    """정규식으로 찾을 수 있는 개인정보(주민번호, 카드, 전화, 계좌, 이메일)를 같은 길이로 가린다.
    길이를 지키므로 위치(오프셋)는 그대로다. 이름(NAME)은 사전 기반이라 여기서 가리지 않는다."""
    chars = list(text)
    for entity_type in _REGEX_ENTITY_TYPES:
        for start, end, _confidence in _detect_regex_matches(text, entity_type):
            chars[start:end] = mask_char * (end - start)
    return "".join(chars)


class PiiDetectConfig(BaseModel):
    entity_types: list[str] | None = None  # None = 전체 6종(RRN/PHONE/EMAIL/ACCOUNT/CARD/NAME)
    action: str = "mask"  # mark_only | mask | tokenize | remove | exclude_from_embedding
    mask_char: str = "*"
    require_admin_approval: bool = False


class PiiDetectBlock(BaseBlock):
    @property
    def block_type(self) -> str:
        return "pii_detect"

    @property
    def category(self) -> str:
        return "구조·보호"

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

            for start, end, entity_type, confidence in sorted(found, key=lambda f: f[0], reverse=True):
                original = text[start:end]
                masked = None
                if cfg.action == "mask":
                    masked = cfg.mask_char * len(original)
                elif cfg.action == "tokenize":
                    masked = f"[MASK:{entity_type}]"
                elif cfg.action == "remove":
                    masked = ""
                if masked is not None:
                    new_text = new_text[:start] + masked + new_text[end:]
                if cfg.action == "exclude_from_embedding":
                    excluded_spans.append([start, end])

                db.add(PiiDetection(
                    run_id=context.run_id, document_id=context.document_id,
                    entity_type=entity_type, action=action_enum,
                    original_encrypted=crypto.encrypt_secret(original),
                    masked_value=masked,
                    confidence=confidence, start_offset=start, end_offset=end,
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
                requires_review=cfg.require_admin_approval and bool(found),
            )
        finally:
            db.close()
