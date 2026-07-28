"""정제·정규화 블록 4종: 텍스트정제/불용어/동의어/사용자사전 — 통합 설계서 §3.3⑥~⑨.

`text_clean`은 레거시 `preprocess` 블록(content_blocks.py, 카테고리 "레거시")을
표준 워크플로우에서 대체한다 — 원문(Document.parsed_text)은 불변으로 두고,
DocumentTextRevision(source="CLEAN")에 정제 결과를 별도 스냅샷으로 남긴다.

`stopword`/`synonym`/`user_dict`는 dictionary_service.py의 BM25 토크나이저(검색
시점, 항상 최신 사전)와는 별개 경로다 — 이 블록들은 문서 처리 시점에
WorkflowRun.dictionary_version에 고정된 사전 스냅샷을 읽고 DictionaryApplication
행으로 적용 이력을 남긴다(설계서 §5/§9.6).
"""
import re
import unicodedata

from pydantic import BaseModel

from app.pipeline.blocks.base import BaseBlock, BlockContext, BlockResult
from app.pipeline.blocks.content_blocks import _carry, _upstream_text

# 전각(U+FF01-FF5E) -> 반각(!-~) 변환 테이블 + 전각 공백(U+3000) -> 일반 공백.
_FULLWIDTH_TRANSLATION = {
    **{i: i - 0xFEE0 for i in range(0xFF01, 0xFF5F)},
    0x3000: 0x20,
}
_SMART_QUOTES = str.maketrans({
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": "-",
})


def _dictionary_version_cutoff(db, dictionary_version: int | None):
    """WorkflowRun.dictionary_version(전역 리비전 번호)을 그 리비전이 만들어진
    시각으로 변환 — 설계서 §5의 "버전 N 시점 유효 항목" 근사에 쓰는 컷오프."""
    from app.db.models.dictionary_revision import DictionaryRevision

    if dictionary_version is None:
        return None
    revision = db.get(DictionaryRevision, dictionary_version)
    return revision.created_at if revision else None


def _load_entries_as_of(db, entry_type: str, cutoff) -> list:
    """설계서 §5 근사식: enabled=true AND (컷오프 없음 OR updated_at <= 컷오프).
    항목별 이력 테이블이 없어 "컷오프 이후 삭제된 항목"은 재구성하지 못하는
    한계가 있음 — §15 리스크 표에 명시된 근사이지 이 함수가 추가로 줄인 범위가
    아니다."""
    from app.db.models.dictionary_entry import DictionaryEntry
    from sqlalchemy.orm import selectinload

    query = db.query(DictionaryEntry).filter(
        DictionaryEntry.entry_type == entry_type, DictionaryEntry.enabled.is_(True)
    ).options(selectinload(DictionaryEntry.variants))
    if cutoff is not None:
        query = query.filter(DictionaryEntry.updated_at <= cutoff)
    return query.all()


def _find_spans(term: str, match_type: str, case_sensitive: bool, text: str) -> list[tuple[int, int]]:
    """entry.match_type 의미를 원문 오프셋 검색에 맞게 적용 — dictionary_service.
    _is_stopword의 토큰 단위 판정을 문자열 구간 탐색으로 옮긴 것.

    EXACT는 뒤쪽 경계를 요구하지 않는다 — 한국어는 교착어라 명사/이름 뒤에
    조사·존칭이 공백 없이 그대로 붙는다("김민준" + "님"처럼). `\\b`는 앞의
    한글 글자와 뒤의 한글 글자 사이를 전이(transition)로 보지 않으므로,
    뒤쪽에도 `\\b`를 요구하면 실제 문장에 등장하는 한글 항목(특히 이름)은
    조사가 붙는 순간 절대 매치되지 않는다. 앞쪽 경계만 유지해 "단어 중간에서
    시작하는 우연한 매치"는 계속 막되, 이 완화로 인해 사전 항목이 문서 내
    더 긴 단어의 접두사와 우연히 일치할 가능성은 근사의 알려진 한계로 남는다."""
    flags = 0 if case_sensitive else re.IGNORECASE
    escaped = re.escape(term)
    if match_type == "REGEX":
        pattern = term
    elif match_type == "PREFIX":
        pattern = r"\b" + escaped
    elif match_type == "SUFFIX":
        pattern = escaped + r"\b"
    elif match_type == "CONTAINS":
        pattern = escaped
    else:  # EXACT
        pattern = r"\b" + escaped
    try:
        return [(m.start(), m.end()) for m in re.finditer(pattern, text, flags)]
    except re.error:
        return []


def _remove_spans(text: str, spans: list[tuple[int, int]]) -> str:
    """겹치지 않는 (start, end) 구간들을 뒤에서부터 잘라내 앞쪽 오프셋이
    흐트러지지 않게 한다."""
    for start, end in sorted(spans, key=lambda s: s[0], reverse=True):
        text = text[:start] + text[end:]
    return text


def _diff_sample(before: str, after: str, window: int = 100) -> tuple[str, str]:
    """변경 위치를 중심으로 한 자른 before/after 쌍을 반환한다. 문서 전체
    앞 200자만 보여주는 head-slice는 ocr_fix/unicode_nfc처럼 문서 전역을
    스캔하는 규칙에서 실제 변경이 200자 이후에만 있으면 before_sample==
    after_sample처럼 보이는 버그를 만든다(9항목 펀치리스트 #8)."""
    min_len = min(len(before), len(after))
    pos = next((i for i in range(min_len) if before[i] != after[i]), min_len)
    start = max(0, pos - window)
    return before[start:start + 2 * window], after[start:start + 2 * window]


class TextCleanConfig(BaseModel):
    collapse_whitespace: bool = True
    normalize_unicode: bool = True  # NFC
    normalize_quotes: bool = True
    normalize_width: bool = True  # 전각 -> 반각
    remove_control_chars: bool = True  # 항상 권장 — 기본값 변경해도 사실상 항상 켜둘 것
    remove_repeated_headers: bool = False
    fix_ocr_errors: bool = False
    apply_custom_rules: bool = True  # cleaning_rules 테이블의 enabled 항목 적용


class TextCleanBlock(BaseBlock):
    @property
    def block_type(self) -> str:
        return "text_clean"

    @property
    def category(self) -> str:
        return "정제·정규화"

    @property
    def config_schema(self):
        return TextCleanConfig

    def run(self, context: BlockContext) -> BlockResult:
        from app.db.models.cleaning_rule import CleaningChange, CleaningRule
        from app.db.models.document import Document
        from app.db.models.document_revision import DocumentTextRevision
        from app.db.session import get_sync_db

        if not context.document_id:
            raise ValueError("실행할 문서가 지정되지 않았습니다.")
        cfg = TextCleanConfig(**(context.config or {}))
        text = _upstream_text(context)

        db = get_sync_db()
        try:
            changes: list[dict] = []

            def _apply(rule_key: str, fn, rule_id=None):
                """fn returns (after, count) or, for rules where individual
                occurrences are cheap to enumerate, (after, count, samples) —
                samples backs the 정제 비교 탭의 [상세] 위치 목록 팝오버(축소
                스코프: 문자 단위 변환은 샘플을 캡처하지 않는다)."""
                nonlocal text
                before = text
                result = fn(before)
                after, count, samples = result if len(result) == 3 else (*result, None)
                if after != before and count:
                    before_sample, after_sample = _diff_sample(before, after)
                    changes.append({
                        "rule_key": rule_key, "rule_id": rule_id,
                        "before_sample": before_sample, "after_sample": after_sample,
                        "change_count": count,
                        "sample_matches": samples[:20] if samples else None,
                    })
                text = after

            if cfg.remove_control_chars:
                _apply("builtin:control_chars", lambda t: re.subn(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", t))
            if cfg.normalize_unicode:
                _apply("builtin:unicode_nfc", lambda t: (unicodedata.normalize("NFC", t), int(unicodedata.normalize("NFC", t) != t)))
            if cfg.normalize_quotes:
                _apply("builtin:quotes", lambda t: (t.translate(_SMART_QUOTES), int(t.translate(_SMART_QUOTES) != t)))
            if cfg.normalize_width:
                _apply("builtin:width", lambda t: (t.translate(_FULLWIDTH_TRANSLATION), int(t.translate(_FULLWIDTH_TRANSLATION) != t)))
            if cfg.fix_ocr_errors:
                # 간단한 규칙 기반 근사(줄바꿈으로 끊긴 하이픈 단어 결합) — 완전한
                # 자모 재결합기는 아님(설계서 §3.3⑥의 fix_ocr_errors 축소 구현).
                _apply("builtin:ocr_fix", lambda t: re.subn(r"-\n", "", t))
            if cfg.collapse_whitespace:
                def _collapse(t: str):
                    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in t.splitlines()]
                    collapsed = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
                    return collapsed, int(collapsed != t)
                _apply("builtin:whitespace", _collapse)
            if cfg.remove_repeated_headers:
                doc = db.get(Document, context.document_id)
                page_map = doc.page_map if doc else None
                if page_map and len(page_map) > 2:
                    def _dedupe_headers(t: str):
                        offsets = [0] + [p[0] for p in page_map]
                        pages = [t[offsets[i]:offsets[i + 1]] for i in range(len(offsets) - 1)]
                        line_counts: dict[str, int] = {}
                        for page in pages:
                            for line in set(page.splitlines()):
                                stripped = line.strip()
                                if stripped:
                                    line_counts[stripped] = line_counts.get(stripped, 0) + 1
                        repeated = {
                            line for line, cnt in line_counts.items()
                            if cnt > max(2, len(pages) // 2)
                        }
                        if not repeated:
                            return t, 0
                        kept = [line for line in t.splitlines() if line.strip() not in repeated]
                        return (
                            "\n".join(kept),
                            sum(1 for line in t.splitlines() if line.strip() in repeated),
                            sorted(repeated)[:20],
                        )
                    _apply("builtin:repeated_headers", _dedupe_headers)

            if cfg.apply_custom_rules:
                rules = (
                    db.query(CleaningRule)
                    .filter(CleaningRule.enabled.is_(True), CleaningRule.rule_type != "BUILTIN")
                    .order_by(CleaningRule.priority.desc())
                    .all()
                )
                def _exact_remove_context_samples(t: str, needle: str, limit: int = 20) -> list[str]:
                    samples = []
                    pos = 0
                    while len(samples) < limit:
                        idx = t.find(needle, pos)
                        if idx == -1:
                            break
                        start, end = max(0, idx - 15), min(len(t), idx + len(needle) + 15)
                        samples.append(t[start:end])
                        pos = idx + len(needle)
                    return samples

                for rule in rules:
                    if rule.rule_type == "REGEX_REPLACE" and rule.pattern:
                        try:
                            re.compile(rule.pattern)
                        except re.error:
                            continue
                        _apply(
                            f"rule:{rule.id}",
                            lambda t, p=rule.pattern, r=rule.replacement or "": (
                                *re.subn(p, r, t),
                                [m.group(0) for m in re.finditer(p, t)][:20],
                            ),
                            rule_id=rule.id,
                        )
                    elif rule.rule_type == "EXACT_REMOVE" and rule.pattern:
                        _apply(
                            f"rule:{rule.id}",
                            lambda t, p=rule.pattern: (
                                t.replace(p, ""), t.count(p), _exact_remove_context_samples(t, p),
                            ),
                            rule_id=rule.id,
                        )
                    elif rule.rule_type == "LINE_FILTER" and rule.pattern:
                        try:
                            regex = re.compile(rule.pattern)
                        except re.error:
                            continue
                        _apply(
                            f"rule:{rule.id}",
                            lambda t, rgx=regex: (
                                "\n".join(line for line in t.splitlines() if not rgx.search(line)),
                                sum(1 for line in t.splitlines() if rgx.search(line)),
                                [line for line in t.splitlines() if rgx.search(line)][:20],
                            ),
                            rule_id=rule.id,
                        )

            for change in changes:
                db.add(CleaningChange(
                    run_id=context.run_id,
                    step_id=context.step_id,
                    document_id=context.document_id,
                    rule_id=change["rule_id"],
                    rule_key=change["rule_key"] if change["rule_id"] is None else None,
                    before_sample=change["before_sample"],
                    after_sample=change["after_sample"],
                    change_count=change["change_count"],
                    sample_matches=change.get("sample_matches"),
                ))
            db.add(DocumentTextRevision(
                document_id=context.document_id, source="CLEAN", parsed_text=text, created_by=None,
            ))
            db.commit()

            return BlockResult(
                output={**_carry(context), "text": text},
                metrics={"changes_applied": len(changes)},
            )
        finally:
            db.close()


class StopwordConfig(BaseModel):
    action: str = "mark"  # mark | exclude_from_analysis | remove
    scope_filter: list[str] | None = None


class StopwordBlock(BaseBlock):
    @property
    def block_type(self) -> str:
        return "stopword"

    @property
    def category(self) -> str:
        return "정제·정규화"

    @property
    def config_schema(self):
        return StopwordConfig

    def run(self, context: BlockContext) -> BlockResult:
        from app.db.models.dictionary_application import DictionaryApplication
        from app.db.models.workflow_run import WorkflowRun
        from app.db.session import get_sync_db

        if not context.document_id:
            raise ValueError("실행할 문서가 지정되지 않았습니다.")
        cfg = StopwordConfig(**(context.config or {}))
        upstream = _carry(context)
        text = _upstream_text(context)
        protected = _merged_protected_spans(context)

        db = get_sync_db()
        try:
            run = db.get(WorkflowRun, context.run_id)
            cutoff = _dictionary_version_cutoff(db, run.dictionary_version if run else None)
            entries = _load_entries_as_of(db, "stopword", cutoff)

            matches: list[tuple[int, int, object]] = []
            for entry in entries:
                if cfg.scope_filter and not (set(entry.scope or []) & set(cfg.scope_filter)):
                    continue
                for start, end in _find_spans(entry.term, entry.match_type or "EXACT", entry.case_sensitive, text):
                    if any(ps <= start < pe or ps < end <= pe for ps, pe in protected):
                        continue
                    matches.append((start, end, entry))

            for start, end, entry in matches:
                db.add(DictionaryApplication(
                    run_id=context.run_id, step_id=context.step_id,
                    document_id=context.document_id, dictionary_type="STOPWORD",
                    entry_id=entry.id, dictionary_version=run.dictionary_version if run else 0,
                    original_text=text[start:end], normalized_text=None,
                    start_offset=start, end_offset=end,
                ))
            db.commit()

            if cfg.action == "remove" and matches:
                text = _remove_spans(text, [(s, e) for s, e, _ in matches])

            return BlockResult(
                output={**upstream, "text": text},
                metrics={"stopword_matches": len(matches), "action": cfg.action},
            )
        finally:
            db.close()


class SynonymConfig(BaseModel):
    processing_mode: str = "normalize"  # normalize | tag_only — dictionary 항목별 processing_mode를 존중할지
    case_sensitive_default: bool = False  # entry.case_sensitive가 항상 채워져 있어 현재는 사실상 미사용


class SynonymBlock(BaseBlock):
    @property
    def block_type(self) -> str:
        return "synonym"

    @property
    def category(self) -> str:
        return "정제·정규화"

    @property
    def config_schema(self):
        return SynonymConfig

    def run(self, context: BlockContext) -> BlockResult:
        from app.db.models.dictionary_application import DictionaryApplication
        from app.db.models.workflow_run import WorkflowRun
        from app.db.session import get_sync_db

        if not context.document_id:
            raise ValueError("실행할 문서가 지정되지 않았습니다.")
        cfg = SynonymConfig(**(context.config or {}))
        upstream = _carry(context)
        text = _upstream_text(context)

        db = get_sync_db()
        try:
            run = db.get(WorkflowRun, context.run_id)
            cutoff = _dictionary_version_cutoff(db, run.dictionary_version if run else None)
            entries = _load_entries_as_of(db, "synonym", cutoff)

            applied = 0
            for entry in entries:
                # 블록 config가 tag_only면 사전 항목의 processing_mode와 무관하게
                # 마킹만 한다. normalize면 REPLACE/NORMALIZE 항목만 실제 치환.
                should_replace = cfg.processing_mode == "normalize" and (
                    entry.processing_mode in ("NORMALIZE", "REPLACE")
                )
                for variant in entry.variants:
                    spans = _find_spans(variant.variant_term, "EXACT", entry.case_sensitive, text)
                    for start, end in spans:
                        db.add(DictionaryApplication(
                            run_id=context.run_id, step_id=context.step_id,
                            document_id=context.document_id, dictionary_type="SYNONYM",
                            entry_id=entry.id, dictionary_version=run.dictionary_version if run else 0,
                            original_text=text[start:end],
                            normalized_text=entry.term if should_replace else None,
                            start_offset=start, end_offset=end,
                        ))
                        applied += 1
                    if should_replace and spans:
                        pattern = re.compile(
                            r"\b" + re.escape(variant.variant_term) + r"\b",
                            0 if entry.case_sensitive else re.IGNORECASE,
                        )
                        text = pattern.sub(entry.term, text)
            db.commit()

            return BlockResult(
                output={**upstream, "text": text},
                metrics={"synonym_applications": applied},
            )
        finally:
            db.close()


class UserDictConfig(BaseModel):
    term_types: list[str] | None = None  # None = 전체 유형
    protect_from_stopwords: bool = True


class UserDictBlock(BaseBlock):
    @property
    def block_type(self) -> str:
        return "user_dict"

    @property
    def category(self) -> str:
        return "정제·정규화"

    @property
    def config_schema(self):
        return UserDictConfig

    def run(self, context: BlockContext) -> BlockResult:
        from app.db.models.dictionary_application import DictionaryApplication
        from app.db.models.workflow_run import WorkflowRun
        from app.db.session import get_sync_db

        if not context.document_id:
            raise ValueError("실행할 문서가 지정되지 않았습니다.")
        cfg = UserDictConfig(**(context.config or {}))
        upstream = _carry(context)
        text = _upstream_text(context)

        db = get_sync_db()
        try:
            run = db.get(WorkflowRun, context.run_id)
            cutoff = _dictionary_version_cutoff(db, run.dictionary_version if run else None)
            entries = _load_entries_as_of(db, "custom_word", cutoff)

            applied = 0
            protected_spans: list[tuple[int, int]] = []
            for entry in entries:
                if entry.processing_rule == "IGNORE":
                    continue
                if cfg.term_types and entry.term_type not in cfg.term_types:
                    continue
                should_replace = entry.processing_rule in ("NORMALIZE", "REPLACE")
                own_spans = _find_spans(entry.term, "EXACT", entry.case_sensitive, text)
                protected_spans.extend(own_spans)
                for start, end in own_spans:
                    db.add(DictionaryApplication(
                        run_id=context.run_id, step_id=context.step_id,
                        document_id=context.document_id, dictionary_type="USER_DICT",
                        entry_id=entry.id, dictionary_version=run.dictionary_version if run else 0,
                        original_text=text[start:end], normalized_text=None,
                        start_offset=start, end_offset=end,
                    ))
                    applied += 1

                # KEEP은 위에서 표준 용어 자체의 등장만 보호 대상으로 등록하고
                # 끝 — 변형 표현 스캔/치환은 NORMALIZE/REPLACE/그 외 규칙에서만.
                if entry.processing_rule == "KEEP":
                    continue
                for variant in entry.variants:
                    spans = _find_spans(variant.variant_term, "EXACT", entry.case_sensitive, text)
                    for start, end in spans:
                        db.add(DictionaryApplication(
                            run_id=context.run_id, step_id=context.step_id,
                            document_id=context.document_id, dictionary_type="USER_DICT",
                            entry_id=entry.id, dictionary_version=run.dictionary_version if run else 0,
                            original_text=text[start:end],
                            normalized_text=entry.term if should_replace else None,
                            start_offset=start, end_offset=end,
                        ))
                        applied += 1
                    if should_replace and spans:
                        pattern = re.compile(
                            r"\b" + re.escape(variant.variant_term) + r"\b",
                            0 if entry.case_sensitive else re.IGNORECASE,
                        )
                        text = pattern.sub(entry.term, text)
                        protected_spans.extend(_find_spans(entry.term, "EXACT", entry.case_sensitive, text))
            db.commit()

            output = {**upstream, "text": text}
            if cfg.protect_from_stopwords and protected_spans:
                # synonym/stopword가 자신의 upstream_outputs를 통해 그대로
                # 이어받는 키 — content_blocks._carry가 다른 키와 함께 복사한다.
                merged = [tuple(s) for s in (upstream.get("protected_spans") or [])]
                merged.extend(protected_spans)
                output["protected_spans"] = [list(s) for s in merged]
            return BlockResult(output=output, metrics={"user_dict_applications": applied})
        finally:
            db.close()


def _merged_protected_spans(context: BlockContext) -> list[tuple[int, int]]:
    """상류(예: user_dict) 출력에 실린 protected_spans를 문자열 매칭 배제용으로
    읽어온다 — 없으면 빈 리스트."""
    for output in context.upstream_outputs.values():
        spans = output.get("protected_spans")
        if spans:
            return [tuple(s) for s in spans]
    return []
