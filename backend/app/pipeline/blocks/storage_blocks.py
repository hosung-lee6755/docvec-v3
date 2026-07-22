"""분할·저장 블록: 문서분할/RAG저장 — 통합 설계서 §3.3⑪·⑬.

Phase 3 promotes document_chunks (Phase 1's table) to the authoritative
chunk store for NEW uploads. continue_processing (app/pipeline/tasks/
process.py) is deliberately untouched — it still serves the existing
/proceed, /reprocess, and collection-reprocess endpoints for already-parsed
documents, a separate legacy path kept as-is per 통합 설계서 §13 Task 3
사용자 결정.
"""
import uuid
from datetime import datetime

from pydantic import BaseModel

from app.pipeline.blocks.base import BaseBlock, BlockContext, BlockResult


class ChunkSplitConfig(BaseModel):
    # fixed/semantic: process.py의 _chunk_text*를 그대로 사용. sentence는
    # 문장 경계만 필요(구조 분석 불필요). paragraph/section_aware/table_unit은
    # structure_analyze가 상류에서 만든 DocumentNode 트리가 반드시 필요하며,
    # 없으면 ChunkSplitBlock.run()이 실행 시점에 에러를 낸다(chunk_strategies.py).
    # None = 컬렉션 기본값 상속 — "fixed"를 기본값으로 두면 run()의
    # `cfg.strategy or coll_strategy`가 항상 참(비어있지 않은 문자열)이 되어
    # 컬렉션에서 고른 전략(예: semantic)이 절대 반영되지 않는 버그가 있었다.
    strategy: str | None = None
    max_tokens: int | None = None  # None = 컬렉션 기본값 상속
    min_tokens: int | None = None
    overlap_tokens: int | None = None
    preserve_table: bool = True
    preserve_heading: bool = True
    include_previous_heading: bool = False
    split_long_paragraph: bool = True


class ChunkSplitBlock(BaseBlock):
    @property
    def block_type(self) -> str:
        return "chunk_split"

    @property
    def category(self) -> str:
        return "분할·저장"

    @property
    def config_schema(self):
        return ChunkSplitConfig

    def run(self, context: BlockContext) -> BlockResult:
        from app.db.models.document import Document
        from app.db.models.document_chunk import DocumentChunk
        from app.db.models.document_node import DocumentNode
        from app.db.session import get_sync_db
        from app.pipeline.blocks.chunk_strategies import _sentence_based_chunks, _tree_based_chunks
        from app.pipeline.tasks.process import (
            _chunk_text,
            _chunk_text_semantic,
            _clean_rag_text,
            _page_number_for_offset,
            _resolve_collection_settings,
        )
        from app.services.embedding import get_embedding_provider

        if not context.document_id:
            raise ValueError("실행할 문서가 지정되지 않았습니다.")
        cfg = ChunkSplitConfig(**(context.config or {}))

        db = get_sync_db()
        try:
            doc = db.get(Document, context.document_id)
            if doc is None:
                raise ValueError("지정된 문서를 찾을 수 없습니다.")

            upstream = next(iter(context.upstream_outputs.values()), {})
            full_text = upstream.get("text") or doc.parsed_text or ""
            # pii_detect(action=exclude_from_embedding)이 표시한 구간 — 이 구간과
            # 겹치는 청크는 excluded_pii=True로 저장해 rag_store가 걸러낸다.
            pii_excluded_spans = [tuple(s) for s in (upstream.get("pii_excluded_spans") or [])]

            embedding_model, coll_max, coll_min, coll_overlap, coll_strategy = (
                _resolve_collection_settings(db, doc)
            )
            strategy = cfg.strategy or coll_strategy
            max_tokens = cfg.max_tokens if cfg.max_tokens is not None else coll_max
            min_tokens = cfg.min_tokens if cfg.min_tokens is not None else coll_min
            overlap_tokens = cfg.overlap_tokens if cfg.overlap_tokens is not None else coll_overlap

            if strategy == "semantic":
                provider = get_embedding_provider(embedding_model)
                spans = [
                    (text, start, end, [], [])
                    for text, start, end in _chunk_text_semantic(
                        full_text, provider, max_chars=max_tokens, min_chars=min_tokens
                    )
                ]
            elif strategy == "sentence":
                spans = [
                    (s.text, s.start, s.end, s.section_path, s.source_node_ids)
                    for s in _sentence_based_chunks(full_text, max_chars=max_tokens, min_chars=min_tokens)
                ]
            elif strategy in ("paragraph", "section_aware", "table_unit"):
                nodes = (
                    db.query(DocumentNode)
                    .filter(DocumentNode.document_id == doc.id, DocumentNode.run_id == context.run_id)
                    .order_by(DocumentNode.sort_order)
                    .all()
                )
                if not nodes:
                    raise ValueError(
                        f"'{strategy}' 분할 전략을 사용하려면 상류에 구조 분석(structure_analyze) "
                        "블록이 있어야 합니다."
                    )
                tree_spans = _tree_based_chunks(
                    nodes, full_text,
                    max_chars=max_tokens, min_chars=min_tokens,
                    respect_headings=strategy == "section_aware" or cfg.preserve_heading,
                    include_previous_heading=cfg.include_previous_heading,
                    preserve_table=cfg.preserve_table,
                    split_long_paragraph=cfg.split_long_paragraph,
                    tables_only=strategy == "table_unit",
                )
                spans = [(s.text, s.start, s.end, s.section_path, s.source_node_ids) for s in tree_spans]
            else:  # "fixed" — 인식되지 않는 값도 여기로 폴백(기존 동작 그대로)
                spans = [
                    (text, start, end, [], [])
                    for text, start, end in _chunk_text(
                        full_text, max_chars=max_tokens, overlap=overlap_tokens, min_chars=min_tokens
                    )
                ]

            cleaned_spans = []
            for text, start, end, section_path, source_node_ids in spans:
                cleaned = _clean_rag_text(text)
                if cleaned:
                    cleaned_spans.append((cleaned, text, start, end, section_path, source_node_ids))

            # Previous run's chunks for this document are stale once this run
            # re-chunks it — clear them (DB analogue of continue_processing's
            # qdrant_service.delete_by_document pre-clear).
            db.query(DocumentChunk).filter(DocumentChunk.document_id == doc.id).delete()
            db.commit()

            chunk_ids: list[str] = []
            for i, (cleaned, raw, start, end, section_path, source_node_ids) in enumerate(cleaned_spans):
                excluded_pii = any(start < pe and ps < end for ps, pe in pii_excluded_spans)
                chunk = DocumentChunk(
                    id=uuid.uuid4(),
                    document_id=doc.id,
                    run_id=context.run_id,
                    chunk_order=i,
                    chunk_text=cleaned,
                    original_text=raw,
                    page_start=_page_number_for_offset(doc.page_map, start),
                    page_end=_page_number_for_offset(doc.page_map, end),
                    section_path=section_path or None,
                    source_node_ids=source_node_ids or None,
                    span_start=start,
                    span_end=end,
                    excluded_pii=excluded_pii,
                )
                db.add(chunk)
                chunk_ids.append(str(chunk.id))
            db.commit()

            return BlockResult(
                output={
                    "document_id": str(doc.id), "chunk_ids": chunk_ids, "chunk_count": len(chunk_ids),
                },
                metrics={"chunk_count": len(chunk_ids), "strategy": strategy},
            )
        finally:
            db.close()


class RagStoreConfig(BaseModel):
    embedding_model: str | None = None  # None = 컬렉션 기본값 상속
    # true면 DocumentChunk.excluded_pii=True인 청크는 임베딩·업서트에서 제외
    # (pii_detect의 action=exclude_from_embedding이 표시한 구간, run() 아래 참고).
    exclude_pii: bool = True
    store_masked_text: bool = False


class RagStoreBlock(BaseBlock):
    @property
    def block_type(self) -> str:
        return "rag_store"

    @property
    def category(self) -> str:
        return "분할·저장"

    @property
    def config_schema(self):
        return RagStoreConfig

    def run(self, context: BlockContext) -> BlockResult:
        from app.core.config import settings
        from app.db.models.document import Document
        from app.db.models.document_chunk import DocumentChunk
        from app.db.session import get_sync_db
        from app.pipeline.tasks.process import _resolve_collection_settings
        from app.services.embedding import get_embedding_provider
        from app.services.qdrant_service import qdrant_service

        if not context.document_id:
            raise ValueError("실행할 문서가 지정되지 않았습니다.")
        cfg = RagStoreConfig(**(context.config or {}))

        db = get_sync_db()
        try:
            doc = db.get(Document, context.document_id)
            if doc is None:
                raise ValueError("지정된 문서를 찾을 수 없습니다.")

            upstream = next(iter(context.upstream_outputs.values()), {})
            chunk_ids = upstream.get("chunk_ids") or []
            chunk_query = db.query(DocumentChunk).filter(DocumentChunk.id.in_(chunk_ids))
            excluded_count = 0
            if cfg.exclude_pii:
                excluded_count = chunk_query.filter(DocumentChunk.excluded_pii.is_(True)).count()
                chunk_query = chunk_query.filter(DocumentChunk.excluded_pii.is_(False))
            chunks = chunk_query.order_by(DocumentChunk.chunk_order).all()

            embedding_model, *_rest = _resolve_collection_settings(db, doc)
            embedding_model = cfg.embedding_model or embedding_model
            provider = get_embedding_provider(embedding_model)

            # Pre-clear before upserting fresh points — same reasoning as
            # continue_processing: without this, a reprocess leaves stale
            # duplicate points searchable alongside the new ones.
            qdrant_service.delete_by_document(settings.qdrant_collection_name, str(doc.id))

            if not chunks:
                doc.status = "INDEXED"
                doc.updated_at = datetime.utcnow()
                db.commit()
                return BlockResult(
                    output={
                        "points_upserted": 0, "collection": settings.qdrant_collection_name,
                        "embedding_model": embedding_model, "dimension": provider.dimension,
                        # Downstream 분석 블록(summarize/extract_keywords/output)이
                        # _upstream_text()로 읽는 키 — 여기서 끊기지 않게 이어준다.
                        "text": doc.parsed_text or "",
                        "document_id": str(doc.id),
                    },
                    metrics={"points_upserted": 0, "excluded_pii_chunks": excluded_count},
                )

            qdrant_service.init_collection(settings.qdrant_collection_name, provider.dimension)
            vectors = provider.embed([c.chunk_text for c in chunks])

            points = [
                {
                    "id": str(chunk.id),
                    "vector": vec,
                    "payload": {
                        "document_id": str(doc.id),
                        "collection_id": str(doc.collection_id) if doc.collection_id else None,
                        "chunk_index": chunk.chunk_order,
                        "text": chunk.chunk_text,
                        "filename": doc.original_filename,
                        "page_number": chunk.page_start,
                        "tags": doc.tags or [],
                        "chunk_id": str(chunk.id),
                        "workflow_run_id": context.run_id,
                    },
                }
                for chunk, vec in zip(chunks, vectors, strict=True)
            ]
            qdrant_service.upsert_points(settings.qdrant_collection_name, points)

            for chunk in chunks:
                chunk.embedded = True
            doc.status = "INDEXED"
            doc.updated_at = datetime.utcnow()
            db.commit()

            return BlockResult(
                output={
                    "points_upserted": len(points), "collection": settings.qdrant_collection_name,
                    "embedding_model": embedding_model, "dimension": provider.dimension,
                    # Downstream 분석 블록(summarize/extract_keywords/output)이
                    # _upstream_text()로 읽는 키 — 여기서 끊기지 않게 이어준다.
                    "text": doc.parsed_text or "",
                    "document_id": str(doc.id),
                },
                metrics={"points_upserted": len(points), "excluded_pii_chunks": excluded_count},
            )
        finally:
            db.close()
