"""품질 검증(quality_check) 블록 겸 검토 게이트 — 통합 설계서 §3.3⑫/§7.4.

파일/텍스트/구조/사전/분할 5개 수준의 지표를 이번 run이 만든 데이터(Document/
DocumentNode/DocumentChunk/DictionaryApplication)에서 직접 계산해 QualityReport
행을 쓴다. 문서 파싱 고도화 Phase 4에서 세 지표가 새로 추가됐다 —
`Document.ocr_page_confidence`(Phase 3)로 페이지 단위 `failed_pages`를,
`Document.tables[*]["detected_as"]`(Phase 3)로 암시적 표 비율을,
`DocumentNode`의 TOC/HEADING 노드(Phase 2)로 목차-제목 일치율을 계산한다 —
이전엔 데이터 소스가 없어 계산 불가능했던 지표들이다. `PARTIAL_FAILURE`는
이제 `failed_pages`가 일부(전체 아님) 있을 때 실제로 도달 가능하다.

일시정지/재개 배관(WAITING_REVIEW 전환, /workflows/runs/{id}/resume)은 이미
실행기(app/pipeline/tasks/workflow.py)에 구현되어 있고 pii_detect의
require_admin_approval이 동일한 BlockResult.requires_review 메커니즘으로 이미
실전 검증했다 — 이 블록은 그 스위치를 켜는 두 번째 생산자일 뿐이다.
"""
import re

from pydantic import BaseModel

from app.pipeline.blocks.base import BaseBlock, BlockContext, BlockResult
from app.pipeline.blocks.content_blocks import _carry

# U+FFFD(대체 문자) + 제어문자 — 텍스트 추출이 깨졌을 때 남는 전형적인 신호.
_BROKEN_CHAR_RE = re.compile(r"[�\x00-\x08\x0b\x0c\x0e-\x1f]")
# TOC 항목의 점선/공백 리더 + 페이지 번호 꼬리, 그리고 번호매김/장절조 머리를
# 각각 벗겨내면 TOC 항목과 실제 HEADING 노드 텍스트를 비교할 수 있는 형태가
# 된다 — structure_blocks.py의 동일 패턴과 의도적으로 맞춘 정규식.
_TOC_TRAILING_LEADER_RE = re.compile(r"[.…\s]{2,}\d{1,4}\s*$")
_LEADING_NUMBER_RE = re.compile(r"^(?:\d+(?:\.\d+)*[.\)]?\s+|제?\s*\d+\s*[장절조편]\s*)")


def _score_from_ratio(ratio: float, *, warn_above: float) -> float:
    """0이면 100점, warn_above에서 60점, 그 두 배 이상이면 0점으로 선형 보간."""
    if ratio <= 0:
        return 100.0
    if warn_above <= 0:
        return 0.0
    if ratio <= warn_above:
        return 100.0 - 40.0 * (ratio / warn_above)
    return max(0.0, 60.0 - 60.0 * ((ratio - warn_above) / warn_above))


def _compute_failed_pages(ocr_page_confidence: list[dict] | None, min_confidence: float) -> list[int]:
    """OCR 신뢰도가 기준 미달인 페이지 번호 목록(문서 파싱 고도화 Phase 4) —
    페이지 단위 부분 실패를 구분해 PARTIAL_FAILURE 판정에 쓴다."""
    if not ocr_page_confidence:
        return []
    return sorted(
        entry["page_number"] for entry in ocr_page_confidence
        if entry.get("confidence") is not None and entry["confidence"] < min_confidence
    )


def _implicit_table_ratio(tables: list[dict] | None) -> float:
    """전체 표 중 선 없이(정렬 기반으로만) 검출된 표의 비율 — 높을수록 표가
    아닌 정렬된 텍스트를 오탐했을 가능성 신호(문서 파싱 고도화 Phase 4)."""
    if not tables:
        return 0.0
    implicit = sum(1 for t in tables if t.get("detected_as") == "implicit_alignment")
    return implicit / len(tables)


def _normalize_heading_like(text: str) -> str:
    stripped = _TOC_TRAILING_LEADER_RE.sub("", text or "").strip()
    stripped = _LEADING_NUMBER_RE.sub("", stripped).strip()
    return stripped


def _toc_heading_match_ratio(toc_texts: list[str], heading_texts: list[str]) -> float | None:
    """TOC 항목 중 실제 HEADING 노드로 확인되는 비율(문서 파싱 고도화
    Phase 4) — 번호매김/장절조 머리와 점선 리더+페이지번호 꼬리를 벗겨낸
    뒤 정확히 일치하는지로 판단하는 근사치. TOC 노드가 없는 문서는 이 지표
    자체가 성립하지 않으므로 None(경고 대상 아님)."""
    if not toc_texts:
        return None
    normalized_headings = {_normalize_heading_like(h) for h in heading_texts}
    matched = sum(1 for t in toc_texts if _normalize_heading_like(t) in normalized_headings)
    return matched / len(toc_texts)


def _determine_status(
    *, chunk_count: int, overall_score: float, fail_below_score: float,
    failed_pages: list[int], total_ocr_pages: int, has_warnings: bool,
) -> str:
    """overall_score는 5개 지표 평균이라, 청크 0개처럼 그 자체로 치명적인
    신호가 다른 지표(예: 표 문법만으로 min_extraction_chars를 넘겨버린
    textExtraction=100)에 희석돼 SUCCESS_WITH_WARNING으로 조용히 넘어갈 수
    있다 — 청크 0개는 평균과 무관하게 먼저 FAILURE로 확정한다(2026-07-28
    test_data E2E 검증, 서울시 도시 범죄 취약지 분석 PDF에서 실제 재현)."""
    if chunk_count == 0:
        return "FAILURE"
    if overall_score < fail_below_score:
        return "FAILURE"
    if failed_pages and len(failed_pages) < total_ocr_pages:
        return "PARTIAL_FAILURE"
    if has_warnings:
        return "SUCCESS_WITH_WARNING"
    return "SUCCESS"


def _decide_review(status: str, review_policy: str, skip_review: bool) -> tuple[str, bool]:
    """FAILURE/PARTIAL_FAILURE는 review_policy와 무관하게 항상 검토를
    강제한다 — skip_review("검토 없이 진행" 업로드 옵션)는 review_policy를
    이 run에 한해 auto_pass로 낮출 뿐이라, 실제로 실패한 문서까지 조용히
    통과되지는 않는다(9항목 펀치리스트 #1)."""
    effective_policy = "auto_pass" if skip_review else review_policy
    if status in ("FAILURE", "PARTIAL_FAILURE"):
        return status, True
    if status == "SUCCESS_WITH_WARNING" and effective_policy in ("review_on_warning", "always_review"):
        return "REVIEW_REQUIRED", True
    if status == "SUCCESS" and effective_policy == "always_review":
        return "REVIEW_REQUIRED", True
    return status, False


class QualityCheckConfig(BaseModel):
    min_extraction_chars: int = 50
    max_broken_char_ratio: float = 0.05
    # ocr_used=True인 문서에만 적용 — Document.ocr_page_confidence(문서 파싱
    # 고도화 Phase 3, pytesseract.image_to_data 기반 실측 페이지 평균)가 있으면
    # 그것을 쓰고, 없으면(Phase 3 이전에 처리된 문서, 또는 전 페이지가 cloud
    # VLM으로 OCR돼 단어별 신뢰도가 없는 경우) format_detect 블록이 남긴
    # has_text_layer 판정용 confidence(WorkflowRunStep.output에서 조회)를
    # 근사치로 폴백한다.
    min_ocr_confidence: float = 0.5
    max_empty_page_ratio: float = 0.2
    min_chunk_chars_warning: int = 50
    max_chunk_chars_warning: int = 2000
    # 문서 파싱 고도화 Phase 4 — 셋 다 대응하는 데이터 소스가 없어 이전엔
    # 계산 불가능했던 지표.
    max_implicit_table_ratio: float = 0.2
    min_toc_heading_match_ratio: float = 0.5
    review_policy: str = "review_on_warning"  # auto_pass | review_on_warning | always_review
    fail_below_score: float = 30.0


class QualityCheckBlock(BaseBlock):
    @property
    def block_type(self) -> str:
        return "quality_check"

    @property
    def block_version(self) -> str:
        # Bumped: failed_pages/implicit_table_ratio/toc_heading_match_ratio
        # are now computed and can newly reach PARTIAL_FAILURE (문서 파싱
        # 고도화 Phase 4) — cached pre-upgrade reports lack these metrics and
        # must not replay.
        #
        # 1.3.0: 분할 수준 점검이 이제 chunk_tier=="child" 청크만 센다 — parent
        # Retrieval 청크(Phase 9)를 포함하면 "너무 긴 청크" 오탐이 생긴다
        # (메타 정보 생성.txt 3절, 2026-07-24).
        #
        # 1.4.0: 청크 0개는 overall_score 평균과 무관하게 무조건 FAILURE로
        # 강제한다 — 캐시된 pre-1.4.0 결과는 청크 0개인 문서도 SUCCESS_WITH_
        # WARNING으로 남아 있을 수 있어 재사용하면 안 된다(2026-07-28).
        return "1.4.0"

    @property
    def category(self) -> str:
        return "품질·제어"

    @property
    def config_schema(self):
        return QualityCheckConfig

    def run(self, context: BlockContext) -> BlockResult:
        from app.db.models.dictionary_application import DictionaryApplication
        from app.db.models.document import Document
        from app.db.models.document_chunk import DocumentChunk
        from app.db.models.document_node import DocumentNode
        from app.db.models.quality_report import QualityReport
        from app.db.models.workflow import WorkflowBlockInstance
        from app.db.models.workflow_run import WorkflowRunStep
        from app.db.session import get_sync_db
        from app.pipeline.tasks.workflow import _resolve_output

        if not context.document_id:
            raise ValueError("실행할 문서가 지정되지 않았습니다.")
        cfg = QualityCheckConfig(**(context.config or {}))

        db = get_sync_db()
        try:
            doc = db.get(Document, context.document_id)
            if doc is None:
                raise ValueError("지정된 문서를 찾을 수 없습니다.")

            warnings: list[str] = []
            warning_categories: list[str] = []

            def add_warning(category: str, message: str) -> None:
                warnings.append(message)
                warning_categories.append(category)

            scores: dict[str, float] = {}

            # --- 텍스트 수준 ---
            text = doc.parsed_text or ""
            text_len = len(text)
            extraction_score = 100.0 if text_len >= cfg.min_extraction_chars else (
                100.0 * text_len / cfg.min_extraction_chars if cfg.min_extraction_chars > 0 else 100.0
            )
            if text_len < cfg.min_extraction_chars:
                add_warning("textExtraction", f"추출된 텍스트가 매우 짧습니다({text_len}자 < {cfg.min_extraction_chars}자 기준).")

            broken_ratio = (len(_BROKEN_CHAR_RE.findall(text)) / text_len) if text_len else 0.0
            broken_score = _score_from_ratio(broken_ratio, warn_above=cfg.max_broken_char_ratio)
            if broken_ratio > cfg.max_broken_char_ratio:
                add_warning("textExtraction", f"깨진 문자 비율이 기준을 초과했습니다({broken_ratio:.1%} > {cfg.max_broken_char_ratio:.1%}).")

            scores["textExtraction"] = round((extraction_score + broken_score) / 2, 1)

            # --- OCR 수준 (사용된 경우에만) ---
            ocr_score = 100.0
            if doc.ocr_used:
                page_confidences = [
                    entry["confidence"] for entry in (doc.ocr_page_confidence or [])
                    if entry.get("confidence") is not None
                ]
                if page_confidences:
                    confidence = sum(page_confidences) / len(page_confidences)
                else:
                    # Phase 3 이전에 처리된 문서, 또는 전 페이지가 cloud VLM으로
                    # OCR돼 단어별 신뢰도가 없는 경우 — format_detect 근사치로 폴백.
                    step = (
                        db.query(WorkflowRunStep)
                        .join(WorkflowBlockInstance, WorkflowRunStep.block_instance_id == WorkflowBlockInstance.id)
                        .filter(
                            WorkflowRunStep.run_id == context.run_id,
                            WorkflowBlockInstance.block_type == "format_detect",
                        )
                        .first()
                    )
                    confidence = _resolve_output(step.output if step else None).get("confidence") if step else None
                if confidence is not None:
                    ocr_score = 100.0 if confidence >= cfg.min_ocr_confidence else 100.0 * confidence / cfg.min_ocr_confidence
                    if confidence < cfg.min_ocr_confidence:
                        add_warning("ocr", f"OCR 신뢰도가 기준 이하입니다({confidence:.2f} < {cfg.min_ocr_confidence:.2f}).")
                else:
                    add_warning("ocr", "OCR을 사용했으나 신뢰도 정보를 확인할 수 없습니다.")
                    ocr_score = 70.0
            scores["ocr"] = round(ocr_score, 1)

            failed_pages = _compute_failed_pages(doc.ocr_page_confidence, cfg.min_ocr_confidence)

            # 빈 페이지 비율: page_map은 텍스트가 있었던 페이지만 기록하므로,
            # 관측된 최대 페이지 번호 대비 빠진 페이지 번호 개수로 역산한다.
            page_map = doc.page_map or []
            page_numbers = {entry[1] for entry in page_map}
            max_page = max(page_numbers) if page_numbers else 0
            empty_page_ratio = ((max_page - len(page_numbers)) / max_page) if max_page else 0.0
            if empty_page_ratio > cfg.max_empty_page_ratio:
                add_warning("structure", f"빈 페이지 비율이 기준을 초과했습니다({empty_page_ratio:.1%} > {cfg.max_empty_page_ratio:.1%}).")

            # --- 구조 수준 ---
            nodes = (
                db.query(DocumentNode)
                .filter(DocumentNode.document_id == doc.id, DocumentNode.run_id == context.run_id)
                .all()
            )
            node_types = {n.node_type for n in nodes}
            if not nodes:
                add_warning("structure", "구조 분석 결과가 없습니다 — 상류에 구조 분석 블록이 있는지 확인하세요.")
                structure_score = 50.0
            else:
                heading_score = 100.0 if "HEADING" in node_types else 60.0
                content_score = 100.0 if any(t in node_types for t in ("PARAGRAPH", "LIST_ITEM")) else 0.0
                empty_page_score = _score_from_ratio(empty_page_ratio, warn_above=cfg.max_empty_page_ratio)
                structure_score = (heading_score + content_score + empty_page_score) / 3
                if "HEADING" not in node_types:
                    add_warning("structure", "제목이 하나도 탐지되지 않았습니다.")
            scores["structure"] = round(structure_score, 1)

            toc_match_ratio = _toc_heading_match_ratio(
                [n.text for n in nodes if n.node_type == "TOC" and n.text],
                [n.text for n in nodes if n.node_type == "HEADING" and n.text],
            )
            if toc_match_ratio is not None and toc_match_ratio < cfg.min_toc_heading_match_ratio:
                add_warning(
                    "structure",
                    f"목차-제목 일치율이 낮습니다({toc_match_ratio:.1%} < {cfg.min_toc_heading_match_ratio:.1%}).",
                )

            implicit_table_ratio = _implicit_table_ratio(doc.tables)
            if doc.tables and implicit_table_ratio > cfg.max_implicit_table_ratio:
                add_warning(
                    "table",
                    f"암시적(선 없는) 표 비율이 높습니다({implicit_table_ratio:.1%} > "
                    f"{cfg.max_implicit_table_ratio:.1%}) — 오탐 가능성을 확인하세요.",
                )

            # --- 사전 수준 (정보성 — 건수 0은 경고 아님) ---
            dict_application_count = (
                db.query(DictionaryApplication)
                .filter(DictionaryApplication.document_id == doc.id, DictionaryApplication.run_id == context.run_id)
                .count()
            )
            scores["normalization"] = 100.0

            # --- 분할 수준 ---
            chunks = (
                db.query(DocumentChunk)
                .filter(
                    DocumentChunk.document_id == doc.id, DocumentChunk.run_id == context.run_id,
                    # Chunk 계층형 Parent Retrieval(메타 정보 생성.txt 3절, Phase 9) —
                    # parent 행은 의도적으로 훨씬 크므로 포함하면 "너무 긴 청크"
                    # 경고가 잘못 뜬다.
                    DocumentChunk.chunk_tier == "child",
                )
                .all()
            )
            short_chunk_ids: list[str] = []
            long_chunk_ids: list[str] = []
            if chunks:
                sizes = [len(c.chunk_text or "") for c in chunks]
                short_chunk_ids = [str(c.id) for c, s in zip(chunks, sizes) if s < cfg.min_chunk_chars_warning]
                long_chunk_ids = [str(c.id) for c, s in zip(chunks, sizes) if s > cfg.max_chunk_chars_warning]
                too_small = len(short_chunk_ids)
                too_large = len(long_chunk_ids)
                bad_ratio = (too_small + too_large) / len(sizes)
                chunking_score = _score_from_ratio(bad_ratio, warn_above=0.1)
                # "chunking_short"/"chunking_long"으로 세분화 — 프런트가 경고를
                # 클릭했을 때 청크 탭으로만 이동하는 게 아니라 metrics.short_chunk_ids/
                # long_chunk_ids로 실제 문제되는 청크로 바로 스크롤·강조할 수 있게
                # 한다(사용자 확인 2026-07-21, "청크텝에서 확인이아니라 문제가 되는
                # 청크로 바로 이동하게 해야지").
                if too_small:
                    add_warning("chunking_short", f"너무 짧은 청크가 {too_small}개 있습니다({cfg.min_chunk_chars_warning}자 미만).")
                if too_large:
                    add_warning("chunking_long", f"너무 큰 청크가 {too_large}개 있습니다({cfg.max_chunk_chars_warning}자 초과).")
            else:
                add_warning("chunking", "생성된 청크가 없습니다.")
                chunking_score = 0.0
            scores["chunking"] = round(chunking_score, 1)

            overall_score = round(sum(scores.values()) / len(scores), 1)

            # --- 상태 판정 ---
            status = _determine_status(
                chunk_count=len(chunks),
                overall_score=overall_score,
                fail_below_score=cfg.fail_below_score,
                failed_pages=failed_pages,
                total_ocr_pages=len(doc.ocr_page_confidence or []),
                has_warnings=bool(warnings),
            )
            if status == "PARTIAL_FAILURE":
                # 일부 페이지만 OCR 신뢰도 기준 미달 — 문서 전체 재작업이
                # 아니라 해당 페이지만 다시 확인하면 되는 부분 실패로 구분한다
                # (문서 파싱 고도화 Phase 4, 모든 페이지가 미달이면 이미 ocr_score
                # 자체가 낮아 위 FAILURE 분기에서 걸린다).
                add_warning("ocr", f"OCR 신뢰도가 낮은 페이지가 있습니다: {failed_pages}.")

            status, requires_review = _decide_review(status, cfg.review_policy, context.skip_review)

            metrics = {
                "overall_score": overall_score,
                "text_chars": text_len,
                "broken_char_ratio": round(broken_ratio, 4),
                "empty_page_ratio": round(empty_page_ratio, 4),
                "node_count": len(nodes),
                "dictionary_application_count": dict_application_count,
                "chunk_count": len(chunks),
                "short_chunk_ids": short_chunk_ids,
                "long_chunk_ids": long_chunk_ids,
                "failed_pages": failed_pages,
                "implicit_table_ratio": round(implicit_table_ratio, 4),
                "toc_heading_match_ratio": (
                    round(toc_match_ratio, 4) if toc_match_ratio is not None else None
                ),
                **scores,
            }

            report = db.query(QualityReport).filter(QualityReport.run_id == context.run_id).one_or_none()
            if report is None:
                report = QualityReport(run_id=context.run_id, document_id=doc.id)
                db.add(report)
            report.overall_score = overall_score
            report.scores = scores
            report.metrics = metrics
            report.warnings = warnings
            report.warning_categories = warning_categories
            report.status = status

            doc.quality_status = status
            db.commit()

            return BlockResult(
                output={
                    **_carry(context),
                    "quality_report_id": str(report.id),
                    "quality_status": status,
                    "overall_score": overall_score,
                },
                warnings=warnings,
                metrics=metrics,
                requires_review=requires_review,
            )
        finally:
            db.close()
