"""Terminal block types: 후처리/출력.

후처리 polishes the accumulated result (whitespace cleanup, list dedup);
출력 writes the final result back to the target document's metadata
(summary/suggested tags) so it shows up in the existing document UI, in
addition to being stored on the run step for the run modal / JSON export.
"""
import logging
import re

from pydantic import BaseModel

from app.pipeline.blocks.base import BaseBlock, BlockContext, BlockResult

logger = logging.getLogger(__name__)


class OutputConfig(BaseModel):
    save_to_document: bool = True


def _match_chunk_keywords(chunk_text: str, document_keywords: list[str]) -> list[str]:
    """청크 텍스트와 문서 레벨 키워드(ExtractKeywordsBlock 출력)를 단순
    substring으로 매칭한다 — 청크마다 새로 LLM을 호출하지 않고 이미 계산된
    문서 레벨 키워드를 재사용하는 저비용 방식. 대소문자 구분 없이 매칭하되
    반환값은 원래 표기를 유지한다."""
    text_lower = chunk_text.lower()
    return [
        kw for kw in document_keywords
        if isinstance(kw, str) and kw.strip() and kw.strip().lower() in text_lower
    ]


def _dedup(items: list) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        cleaned = str(item).strip()
        key = cleaned.lower()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return result


class PostprocessBlock(BaseBlock):
    @property
    def block_type(self) -> str:
        return "postprocess"

    @property
    def category(self) -> str:
        return "분석"

    def run(self, context: BlockContext) -> BlockResult:
        output = dict(next(iter(context.upstream_outputs.values()), {}))
        if isinstance(output.get("summary"), str):
            # Strip boilerplate lead-ins the model tends to emit, then
            # normalize whitespace.
            summary = re.sub(r"^\s*(요약\s*[:：]|다음은.*?요약입니다\.?)\s*", "", output["summary"])
            output["summary"] = re.sub(r"[ \t]+", " ", summary).strip()
        for key in ("keywords", "entities", "problems"):
            if isinstance(output.get(key), list):
                output[key] = _dedup(output[key])
        return BlockResult(output=output)


class OutputBlock(BaseBlock):
    @property
    def block_type(self) -> str:
        return "output"

    @property
    def category(self) -> str:
        return "분석"

    @property
    def block_version(self) -> str:
        # Bumped: upstream-merge fix below changes this block's output for any
        # graph where `output` has more than one incoming edge — must
        # invalidate BlockExecutionCache so already-cached (deficient) runs
        # actually re-execute instead of replaying the old result.
        #
        # 1.2.0: classify 블록의 category 출력을 이제 tags 병합과 별도로
        # Document.category에도 스탬프한다 — 캐시된 이전 결과를 재생하면
        # category가 채워지지 않는다.
        #
        # 1.3.0: 문서 레벨 키워드를 이 run의 DocumentChunk.keywords에도
        # substring 매칭으로 역전파한다 — 캐시된 이전 결과는 청크 keywords를
        # 채우지 않는다.
        #
        # 1.4.0: summary가 이번 run에서 갱신되면 Summary Index(Qdrant
        # document_summaries 컬렉션)에도 upsert한다 — 캐시된 이전 결과는
        # 이 색인을 만들지 않는다.
        #
        # 1.5.0: 키워드 역전파가 이제 chunk_tier=="child" 청크만 대상으로
        # 한다 — parent Retrieval 청크는 제외.
        #
        # 1.6.0: 사용자가 직접 고친 분류(user_edited_fields)는 Document.category 에 덮어쓰지 않는다 —
        # 캐시된 이전 결과를 재생하면 사용자 수정이 있어도 분류가 되돌려진다.
        return "1.6.0"

    @property
    def config_schema(self) -> type[BaseModel] | None:
        return OutputConfig

    def run(self, context: BlockContext) -> BlockResult:
        from app.db.models.document import Document
        from app.db.models.document_chunk import DocumentChunk
        from app.db.session import get_sync_db

        # A graph can feed `output` from more than one branch (e.g. a direct
        # input->output edge alongside the real classify/extract/summarize
        # chain) — taking just one arbitrary upstream silently dropped
        # whichever branch didn't win, so results varied by document even on
        # the same workflow. Merge every branch instead: list-valued keys
        # (keywords/entities/...) concatenate and dedupe, scalar keys keep the
        # first non-empty value found.
        upstream: dict = {}
        for branch_output in context.upstream_outputs.values():
            for key, value in branch_output.items():
                if isinstance(value, list):
                    existing = upstream.get(key)
                    if isinstance(existing, list):
                        upstream[key] = existing + [v for v in value if v not in existing]
                    else:
                        upstream[key] = list(value)
                elif not upstream.get(key):
                    upstream[key] = value
        result = {k: v for k, v in upstream.items() if k != "text"}
        saved_fields: list[str] = []
        # Before/after per modified document field, so the run history screen
        # can show exactly what this run changed (원본 보존·이력 추적 원칙 —
        # see 문서데이터 전처리 방안.md).
        changes: list[dict] = []

        # Default destination: write results onto the document the run was
        # started against. Opt out per block with config {"save_to_document": false}.
        if context.document_id and context.config.get("save_to_document", True) is not False:
            db = get_sync_db()
            try:
                doc = db.get(Document, context.document_id)
                if doc is not None:
                    summary = upstream.get("summary")
                    if isinstance(summary, str) and summary.strip():
                        changes.append({
                            "field": "summary",
                            "before": doc.summary,
                            "after": summary.strip(),
                        })
                        doc.summary = summary.strip()
                        doc.summary_status = "DONE"
                        saved_fields.append("summary")

                    tags: list[str] = []
                    for key in ("keywords", "entities"):
                        if isinstance(upstream.get(key), list):
                            tags.extend(str(t) for t in upstream[key])
                    category = upstream.get("category")
                    if isinstance(category, str) and category.strip():
                        tags.append(category.strip())
                        # 사용자가 직접 고친 분류(user_edited_fields)는 재처리가 덮어쓰지 않는다.
                        if "category" not in (getattr(doc, "user_edited_fields", None) or []):
                            doc.category = category.strip()[:50]
                            saved_fields.append("category")
                    if tags:
                        before_tags = list(doc.suggested_tags or [])
                        existing = {t.lower() for t in (doc.tags or [])}
                        merged = _dedup(before_tags + tags)
                        doc.suggested_tags = [t for t in merged if t.lower() not in existing] or None
                        doc.metadata_status = "DONE"
                        saved_fields.append("suggested_tags")
                        changes.append({
                            "field": "suggested_tags",
                            "before": before_tags,
                            "after": list(doc.suggested_tags or []),
                        })

                    # 문서 레벨 키워드가 확정된 지금(OutputBlock은 DAG의 마지막
                    # 블록)에서야 청크별 매칭이 가능하다. chunk_split은 이 블록보다
                    # 항상 먼저 끝나므로 이 run의 청크는 이미 전부 존재한다.
                    document_keywords = [
                        k for k in (upstream.get("keywords") or []) if isinstance(k, str) and k.strip()
                    ]
                    if document_keywords and context.run_id:
                        run_chunks = db.query(DocumentChunk).filter(
                            DocumentChunk.document_id == doc.id,
                            DocumentChunk.run_id == context.run_id,
                            # Phase 9 — parent 청크는 키워드 매칭 대상에서 제외
                            # (부모는 UI에 노출되지 않아 keywords가 쓰이지 않음).
                            DocumentChunk.chunk_tier == "child",
                        ).all()
                        for chunk in run_chunks:
                            matched = _match_chunk_keywords(chunk.chunk_text, document_keywords)
                            if matched:
                                chunk.keywords = matched
                        if run_chunks:
                            saved_fields.append("chunk_keywords")

                    if saved_fields:
                        db.commit()

                    # Summary Index — 실패해도 이 run의 나머지 결과는 이미 커밋됐으므로
                    # 되돌리지 않는다(best-effort, Qdrant 장애가 워크플로우 run 자체를
                    # 실패시키면 안 됨).
                    if "summary" in saved_fields:
                        try:
                            from app.services.summary_index import index_document_summary

                            index_document_summary(str(doc.id), doc.summary)
                        except Exception:
                            logger.exception(
                                "summary index upsert failed", extra={"document_id": str(doc.id)}
                            )
            finally:
                db.close()

        return BlockResult(output={
            **result, "saved_to_document": saved_fields, "changes": changes,
        })
