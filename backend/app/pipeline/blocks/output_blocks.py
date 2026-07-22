"""Terminal block types: 후처리/출력.

후처리 polishes the accumulated result (whitespace cleanup, list dedup);
출력 writes the final result back to the target document's metadata
(summary/suggested tags) so it shows up in the existing document UI, in
addition to being stored on the run step for the run modal / JSON export.
"""
import re

from pydantic import BaseModel

from app.pipeline.blocks.base import BaseBlock, BlockContext, BlockResult


class OutputConfig(BaseModel):
    save_to_document: bool = True


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
        return "1.1.0"

    @property
    def config_schema(self) -> type[BaseModel] | None:
        return OutputConfig

    def run(self, context: BlockContext) -> BlockResult:
        from app.db.models.document import Document
        from app.db.session import get_sync_db

        # A graph can feed `output` from more than one branch (e.g. a direct
        # input->output edge alongside the real classify/extract/summarize
        # chain) — taking just one arbitrary upstream silently dropped
        # whichever branch didn't win, so results varied by document even on
        # the same workflow (사용자 확인 2026-07-22, 요약/태그가 문서마다
        # 들쭉날쭉하던 원인). Merge every branch instead: list-valued keys
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

                    if saved_fields:
                        db.commit()
            finally:
                db.close()

        return BlockResult(output={
            **result, "saved_to_document": saved_fields, "changes": changes,
        })
