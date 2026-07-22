"""품질 검증(quality_check) 블록 겸 검토 게이트 — 통합 설계서 §3.3⑫/§7.4.

파일/텍스트/구조/사전/분할 5개 수준의 지표를 이번 run이 만든 데이터(Document/
DocumentNode/DocumentChunk/DictionaryApplication)에서 직접 계산해 QualityReport
행을 쓴다. 마스터 설계서(문서데이터 전처리 방안.md §12.2)가 나열한 지표 중
현재 이 코드베이스에 데이터 소스가 없는 것(목차-제목 일치율, 미등록 도메인
용어 수, 사전 충돌/중복 건수, 페이지 단위 부분 실패 등)은 계산하지 않는다 —
Phase 6까지의 범위 축소 원칙과 동일. `PARTIAL_FAILURE`는 그래서 이 블록이
실제로 내리는 판정에는 등장하지 않는다(enum에는 이미 존재, §18.3의
`metrics.failed_pages`가 어떤 블록에도 구현되지 않았기 때문 — 향후 페이지
단위 실패 격리가 생기면 그때 이 블록에서 판정 분기를 추가한다).

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


def _score_from_ratio(ratio: float, *, warn_above: float) -> float:
    """0이면 100점, warn_above에서 60점, 그 두 배 이상이면 0점으로 선형 보간."""
    if ratio <= 0:
        return 100.0
    if warn_above <= 0:
        return 0.0
    if ratio <= warn_above:
        return 100.0 - 40.0 * (ratio / warn_above)
    return max(0.0, 60.0 - 60.0 * ((ratio - warn_above) / warn_above))


class QualityCheckConfig(BaseModel):
    min_extraction_chars: int = 50
    max_broken_char_ratio: float = 0.05
    # ocr_used=True인 문서에만 적용 — 실제 페이지별 OCR 신뢰도는 어디에도
    # 저장되지 않는다(pdf_adapter.py가 pytesseract.image_to_string만 쓰고
    # image_to_data를 쓰지 않음). format_detect 블록이 남긴 has_text_layer
    # 판정용 confidence(WorkflowRunStep.output에서 조회)를 근사치로 쓴다.
    min_ocr_confidence: float = 0.5
    max_empty_page_ratio: float = 0.2
    min_chunk_chars_warning: int = 50
    max_chunk_chars_warning: int = 2000
    review_policy: str = "review_on_warning"  # auto_pass | review_on_warning | always_review
    fail_below_score: float = 30.0


class QualityCheckBlock(BaseBlock):
    @property
    def block_type(self) -> str:
        return "quality_check"

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
                .filter(DocumentChunk.document_id == doc.id, DocumentChunk.run_id == context.run_id)
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

            # --- 상태 판정 (PARTIAL_FAILURE는 이 블록에서 도달 불가 — 모듈 docstring 참고) ---
            if overall_score < cfg.fail_below_score:
                status = "FAILURE"
            elif warnings:
                status = "SUCCESS_WITH_WARNING"
            else:
                status = "SUCCESS"

            requires_review = False
            if status == "FAILURE":
                requires_review = True
            elif status == "SUCCESS_WITH_WARNING" and cfg.review_policy in ("review_on_warning", "always_review"):
                status = "REVIEW_REQUIRED"
                requires_review = True
            elif status == "SUCCESS" and cfg.review_policy == "always_review":
                status = "REVIEW_REQUIRED"
                requires_review = True

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
