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
    # 문서 파싱 고도화 Phase 3 — 오버사이즈 TABLE 노드를 문자수 컷 대신 행
    # 단위로 나눌 때 그룹당 최대 행 수. None(기본)이면 행 수 대신 max_tokens
    # 문자수 기준으로 그리디 그룹화한다(표마다 셀 폭이 달라 "행 수"보다
    # 렌더링 결과 길이가 청크 크기 목표(max_tokens)에 더 직접적으로 맞음).
    table_chunk_max_rows: int | None = None


class ChunkSplitBlock(BaseBlock):
    @property
    def block_type(self) -> str:
        return "chunk_split"

    @property
    def block_version(self) -> str:
        # 1.1.0: _tree_based_chunks의 꼬리 병합이 preserve_table을 무시하고
        # TABLE 노드의 청크를 뒤따르는 짧은 문단과 합칠 수 있던 버그를 수정
        # (chunk_strategies.py, 문서 파싱 고도화 회고 2026-07-23) — 캐시된
        # pre-1.1.0 결과는 이 수정을 반영하지 않으므로 재사용하면 안 된다.
        #
        # 1.2.0: 오버사이즈 TABLE 노드가 이제 문자수 컷 대신 헤더 반복 포함
        # 행 그룹으로 나뉜다(신규 table_chunk_max_rows 설정) — 캐시된
        # pre-1.2.0 결과는 표가 여전히 문자수로 잘려 있어 재사용하면 안 된다
        # (Docling 도입 설계서, 2026-07-23 Phase 3).
        #
        # 1.3.0: DocumentChunk.token_count/chunk_type/element_id/
        # workflow_version/dictionary_version/prev_chunk_id/next_chunk_id를
        # 이제 채운다 — 캐시된 pre-1.3.0 결과는 이 컬럼들이 전부 비어 있다
        # (메타 정보 생성 설계서, 2026-07-23 Phase 4).
        #
        # 1.4.0: DocumentChunk.char_count/language/source_file도 이제 채운다 —
        # 캐시된 pre-1.4.0 결과는 이 컬럼들이 비어 있다(메타 정보 생성.txt
        # 3절, 2026-07-24).
        #
        # 1.5.0: Parent Retrieval — 같은 section_path를 공유하는 연속 child를
        # 묶는 parent 청크 행을 이제 함께 만든다(chunk_tier/parent_chunk_id) —
        # 캐시된 pre-1.5.0 결과는 parent 행이 전혀 없다(메타 정보 생성.txt 3절
        # Phase 9, 2026-07-24).
        return "1.5.0"

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
        from app.db.models.workflow import WorkflowVersion
        from app.db.models.workflow_run import WorkflowRun
        from app.db.session import get_sync_db
        from app.pipeline.blocks.chunk_strategies import (
            _estimate_token_count,
            _sentence_based_chunks,
            _tree_based_chunks,
            group_children_into_parents,
        )
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

            # 메타 정보 생성 설계서(2026-07-23) Phase 4 — tree 기반 전략만 실제
            # DocumentNode를 참조하므로(source_node_ids), chunk_type/element_id는
            # 이 맵이 채워졌을 때만 의미가 있다. sentence/fixed/semantic 전략은
            # 노드 트리가 없어 항상 None으로 남는다(문서화된 한계).
            node_by_id: dict[str, DocumentNode] = {}

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
                node_by_id = {str(n.id): n for n in nodes}
                tree_spans = _tree_based_chunks(
                    nodes, full_text,
                    max_chars=max_tokens, min_chars=min_tokens,
                    respect_headings=strategy == "section_aware" or cfg.preserve_heading,
                    include_previous_heading=cfg.include_previous_heading,
                    preserve_table=cfg.preserve_table,
                    split_long_paragraph=cfg.split_long_paragraph,
                    tables_only=strategy == "table_unit",
                    tables=doc.tables,
                    table_chunk_max_rows=cfg.table_chunk_max_rows,
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

            # 메타 정보 생성 설계서(2026-07-23) Phase 4 — 이 run이 실제로 사용한
            # workflow version 번호/dictionary 리비전은 run 레벨에 이미 있는
            # 값이라 새로 계산하지 않고 그대로 청크에 복사한다.
            run_row = db.get(WorkflowRun, context.run_id) if context.run_id else None
            dictionary_version = run_row.dictionary_version if run_row else None
            workflow_version_number = None
            if run_row is not None:
                version_row = db.get(WorkflowVersion, run_row.version_id)
                workflow_version_number = version_row.version_number if version_row else None

            # Chunk 계층형 Parent Retrieval(메타 정보 생성.txt 3절, Phase 9,
            # 사용자 확정 2026-07-24) — 같은 section_path를 공유하는 연속
            # child들을 하나의 parent로 묶는다. parent는 임베딩되지 않고(항상
            # embedded=False, chunk_ids 출력에도 포함 안 함) DB에만 컨텍스트
            # 확장용으로 존재 — rag_store가 이 chunk_ids만 임베딩하므로 parent를
            # 걸러내기 위한 별도 필터가 rag_store 쪽엔 필요 없다.
            parent_groups = group_children_into_parents(cleaned_spans, max_tokens)
            group_of_index: dict[int, int] = {
                idx: g for g, indices in enumerate(parent_groups) for idx in indices
            }
            parent_by_group: dict[int, DocumentChunk] = {}

            chunk_ids: list[str] = []
            created_chunks: list[DocumentChunk] = []
            for i, (cleaned, raw, start, end, section_path, source_node_ids) in enumerate(cleaned_spans):
                g = group_of_index[i]
                if g not in parent_by_group:
                    group_indices = parent_groups[g]
                    g_start = cleaned_spans[group_indices[0]][2]
                    g_end = cleaned_spans[group_indices[-1]][3]
                    parent = DocumentChunk(
                        id=uuid.uuid4(),
                        document_id=doc.id,
                        run_id=context.run_id,
                        # child의 실제 순서(chunk_order)와 겹치지 않도록 큰 값으로
                        # 오프셋 — parent는 청크 목록/순회에 노출되지 않아 순서
                        # 자체는 의미가 없다.
                        chunk_order=1_000_000 + g,
                        chunk_text=full_text[g_start:g_end],
                        original_text=full_text[g_start:g_end],
                        page_start=_page_number_for_offset(doc.page_map, g_start),
                        page_end=_page_number_for_offset(doc.page_map, g_end),
                        section_path=cleaned_spans[group_indices[0]][4] or None,
                        span_start=g_start,
                        span_end=g_end,
                        chunk_tier="parent",
                        embedded=False,
                        char_count=g_end - g_start,
                        language=doc.language,
                        source_file=doc.original_filename,
                    )
                    db.add(parent)
                    parent_by_group[g] = parent
                parent_chunk = parent_by_group[g]

                excluded_pii = any(start < pe and ps < end for ps, pe in pii_excluded_spans)
                # 청크가 파생된 첫 DocumentNode의 타입/element_id를 그대로
                # 복사한다(별도 분류 로직 없음) — tree 기반 전략이 아니면
                # source_node_ids가 비어 있어 둘 다 None으로 남는다.
                source_node = node_by_id.get(source_node_ids[0]) if source_node_ids else None
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
                    token_count=_estimate_token_count(cleaned),
                    chunk_type=source_node.node_type if source_node is not None else None,
                    element_id=getattr(source_node, "element_id", None) if source_node is not None else None,
                    workflow_version=workflow_version_number,
                    dictionary_version=dictionary_version,
                    # 메타 정보 생성.txt 3절 후속(2026-07-24) — 이미 로드되어 있는
                    # 값을 그대로 복사(추가 쿼리 없음). embedding_model/version은
                    # rag_store 단계에서 스탬프(임베딩 모델이 아직 정해지지 않은
                    # 시점이라 여기서는 채울 수 없음).
                    char_count=len(cleaned),
                    language=doc.language,
                    source_file=doc.original_filename,
                    parent_chunk_id=parent_chunk.id,
                    chunk_tier="child",
                )
                db.add(chunk)
                chunk_ids.append(str(chunk.id))
                created_chunks.append(chunk)

            # prev/next_chunk_id는 아직 세팅하지 않은 채로 먼저 flush한다 —
            # 세팅 후 flush하면 SQLAlchemy가 parent+child 전체를 한 INSERT
            # 배치(insertmanyvalues)로 묶어 보내는데, next_chunk_id가 배치 내
            # 뒤쪽에 나오는(아직 안 만들어진) 행을 가리키면 FK 제약조건
            # ("document_chunks_next_chunk_id_fkey")이 즉시 위반된다(DEFERRABLE
            # 아님) — 실제 문서 재처리 중 발견(2026-07-25). 먼저 전부
            # NULL 상태로 INSERT해 행을 만든 뒤, 아래에서 UPDATE로 연결한다.
            db.flush()

            # 인접 청크를 순서대로 연결(꼬리 병합 이후 확정된 chunk_order 기준) —
            # 별도 블록 없이 저장 루프 끝에서 한 번만 수행.
            for i, chunk in enumerate(created_chunks):
                chunk.prev_chunk_id = created_chunks[i - 1].id if i > 0 else None
                chunk.next_chunk_id = created_chunks[i + 1].id if i + 1 < len(created_chunks) else None

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
    def block_version(self) -> str:
        # 1.1.0: 임베딩에 사용한 모델명을 이제 DocumentChunk.embedding_model에도
        # 스탬프한다(기존엔 Qdrant 페이로드에만 있었음) — 캐시된 pre-1.1.0
        # 결과는 이 컬럼이 항상 비어 있다(메타 정보 생성 설계서, 2026-07-23
        # Phase 4).
        #
        # 1.2.0: DocumentChunk.version(임베딩 차원수 문자열)도 이제 스탬프한다 —
        # 캐시된 pre-1.2.0 결과는 이 컬럼이 항상 비어 있다(메타 정보 생성.txt
        # 3절, 2026-07-24).
        return "1.2.0"

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
                # 메타 정보 생성 설계서(2026-07-23) Phase 4 — 이미 계산된 값을
                # Qdrant 페이로드뿐 아니라 DB 컬럼에도 그대로 남긴다.
                chunk.embedding_model = embedding_model
                # 메타 정보 생성.txt 3절 version(임베딩 버전) — 별도 버전 태그가
                # 없어(사용자 결정, 2026-07-24) 임베딩 차원수를 버전 대용으로
                # 스탬프한다. 모델이 바뀌어 차원수가 달라지면 값도 함께 바뀐다.
                chunk.version = str(provider.dimension)
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
