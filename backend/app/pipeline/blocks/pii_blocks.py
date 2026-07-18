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
        return [(m.start(), m.end(), 0.9) for m in _PHONE_RE.finditer(text)]
    if entity_type == "ACCOUNT":
        return [(m.start(), m.end(), 0.5) for m in _ACCOUNT_RE.finditer(text)]
    if entity_type == "EMAIL":
        return [(m.start(), m.end(), 0.98) for m in _EMAIL_RE.finditer(text)]
    return []


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
