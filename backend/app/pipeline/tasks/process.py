import bisect
import logging
import re
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

from app.core.config import settings
from app.pipeline.celery_app import celery_app

logger = logging.getLogger(__name__)


# Search up to max_chars / this ratio backward for a paragraph boundary before
# falling back to a hard character cut — see _chunk_text.
_BOUNDARY_LOOKBACK_RATIO = 4


def _chunk_text(
    text: str, max_chars: int = 2000, overlap: int = 200, min_chars: int = 0
) -> list[tuple[str, int, int]]:
    """Returns (chunk_text, start_offset, end_offset) tuples so callers can map a
    chunk back to a source page via _page_number_for_offset.

    Prefers cutting at a paragraph boundary ("\n\n", inserted between blocks by
    text_extract block — see _build_page_map) near the target size, so a [표 N] table
    block or a paragraph isn't split mid-way. Falls back to a hard character cut
    when no boundary is found within the lookback window.
    """
    if not text.strip():
        return []
    chunks: list[tuple[str, int, int]] = []
    start = 0
    while start < len(text):
        hard_end = min(start + max_chars, len(text))
        end = hard_end
        if hard_end < len(text):
            lookback = max_chars // _BOUNDARY_LOOKBACK_RATIO
            search_start = max(start, hard_end - lookback)
            boundary = text.rfind("\n\n", search_start, hard_end)
            if boundary != -1 and boundary > start:
                end = boundary + 2
        chunks.append((text[start:end], start, end))
        if end == len(text):
            break
        start = end - overlap
    if len(chunks) > 1 and len(chunks[-1][0]) < min_chars:
        prev_text, prev_start, _prev_end = chunks[-2]
        last_text, _last_start, last_end = chunks[-1]
        chunks[-2] = (prev_text + last_text, prev_start, last_end)
        chunks.pop()
    return chunks


# Sentence boundaries for semantic chunking: sentence-final punctuation
# followed by whitespace, or a paragraph break.
_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?。！？])\s+|\n\n+")
# Adjacent-sentence similarities below this percentile are chunk-boundary
# candidates — adaptive per document rather than a fixed cosine threshold.
_SEMANTIC_SIM_PERCENTILE = 25


def _sentence_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    start = 0
    for m in _SENTENCE_BOUNDARY_RE.finditer(text):
        if m.start() > start:
            spans.append((start, m.start()))
        start = m.end()
    if start < len(text):
        spans.append((start, len(text)))
    return [(s, e) for s, e in spans if text[s:e].strip()]


def _chunk_text_semantic(
    text: str, provider, max_chars: int, min_chars: int
) -> list[tuple[str, int, int]]:
    """Semantic chunking: embeds each sentence and cuts where adjacent-sentence
    cosine similarity drops (topic shift), constrained by the collection's
    min/max size settings. Returns the same (chunk, start, end) offset tuples
    as _chunk_text so page attribution keeps working. A single oversize
    "sentence" (e.g. a [표 N] block, which has no sentence enders) is kept
    whole rather than split mid-table."""
    import numpy as np

    if not text.strip():
        return []
    spans = _sentence_spans(text)
    if len(spans) < 3:
        return _chunk_text(text, max_chars=max_chars, overlap=0, min_chars=min_chars)

    sentences = [text[s:e] for s, e in spans]
    vectors = np.asarray(provider.embed(sentences), dtype=float)
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True) + 1e-9
    sims = (vectors[:-1] * vectors[1:]).sum(axis=1)
    threshold = float(np.percentile(sims, _SEMANTIC_SIM_PERCENTILE))

    chunks: list[tuple[str, int, int]] = []
    cur_start = spans[0][0]
    for i, (_s, e) in enumerate(spans):
        is_last = i == len(spans) - 1
        cur_len = e - cur_start
        semantic_break = not is_last and sims[i] < threshold and cur_len >= min_chars
        size_break = cur_len >= max_chars
        if is_last or semantic_break or size_break:
            chunks.append((text[cur_start:e], cur_start, e))
            if not is_last:
                cur_start = spans[i + 1][0]
    return chunks


def _build_page_map(pages) -> list[list[int]]:
    """Builds [[end_offset, page_number], ...] pairs matching the exact character
    offsets that `"\n\n".join(...)` (see the text_extract block) produces, so a chunk's
    start_offset into parsed_text can be mapped back to a source page number via
    bisect. One entry per page transition, in ascending end_offset order."""
    blocks = [
        (page.page_number, block.text)
        for page in pages
        for block in page.text_blocks
        if block.text.strip()
    ]
    page_map: list[list[int]] = []
    offset = 0
    current_page: int | None = None
    for i, (page_num, text) in enumerate(blocks):
        if current_page is None:
            current_page = page_num
        elif page_num != current_page:
            page_map.append([offset, current_page])
            current_page = page_num
        if i > 0:
            offset += 2  # separator "\n\n" added by "\n\n".join
        offset += len(text)
    if current_page is not None:
        page_map.append([offset, current_page])
    return page_map


def _page_number_for_offset(page_map: list[list[int]] | None, offset: int) -> int | None:
    if not page_map:
        return None
    end_offsets = [entry[0] for entry in page_map]
    idx = bisect.bisect_right(end_offsets, offset)
    if idx >= len(page_map):
        idx = len(page_map) - 1
    return page_map[idx][1]


def _resolve_collection_settings(db, doc) -> tuple[str, int, int, int, str]:
    from app.db.models.collection import Collection

    if doc.collection_id:
        collection = db.get(Collection, doc.collection_id)
        if collection:
            return (
                collection.embedding_model,
                collection.chunk_max_tokens,
                collection.chunk_min_tokens,
                collection.chunk_overlap_tokens,
                collection.chunk_strategy or "size",
            )
    return (
        settings.default_embedding_model,
        settings.default_chunk_max_tokens,
        settings.default_chunk_min_tokens,
        settings.default_chunk_overlap_tokens,
        "size",
    )


def _resolve_vision_credentials(db, doc) -> dict:
    """Looks up a registered OpenAI/Anthropic key (project first, then user —
    same priority as chat.py's generate_answer) to opt a document into the
    cloud-VLM OCR path in pdf_adapter.py. Returns {} when no key is registered,
    which leaves adapter behavior unchanged (Tesseract-only)."""
    from app.core.crypto import decrypt_secret
    from app.db.models.collection import Collection
    from app.db.models.project_api_key import ProjectApiKey
    from app.db.models.user_api_key import UserApiKey

    project_id = None
    if doc.collection_id:
        collection = db.get(Collection, doc.collection_id)
        if collection:
            project_id = collection.project_id

    for backend in ("openai", "anthropic"):
        key_row = None
        if project_id:
            key_row = (
                db.query(ProjectApiKey)
                .filter_by(project_id=project_id, provider=backend)
                .first()
            )
        if not key_row:
            key_row = (
                db.query(UserApiKey)
                .filter_by(user_id=doc.created_by, provider=backend)
                .first()
            )
        if key_row:
            return {"vision_backend": backend, "vision_api_key": decrypt_secret(key_row.encrypted_key)}
    return {}


# Figure recognition guards: drop icons/decorations (tiny dimensions or byte
# size), dedupe repeated images (page logos), and cap per-document volume so a
# graphics-heavy file can't stall the worker on serial OCR/VLM calls.
_FIGURE_MIN_DIMENSION = 64
_FIGURE_MIN_BYTES = 3072
_FIGURE_MAX_COUNT = 40
# Recognized text shorter than this is treated as "nothing meaningful" and not
# merged into parsed_text (the image record itself is still kept for viewing).
_FIGURE_MIN_MEANINGFUL_CHARS = 10

_FIGURE_VISION_PROMPT = (
    "이 이미지는 문서에 삽입된 그림/차트/도표입니다. 이미지가 전달하는 내용을 한국어로 간결히 설명하고, "
    "이미지 안에 텍스트나 수치가 있다면 정확히 그대로 옮겨 적으세요."
)


def _recognize_figure_text(png_bytes: bytes, vision_options: dict) -> str:
    """Cloud VLM first (BYOK key registered — same opt-in as scan OCR), then
    local Tesseract. Returns "" when neither produces anything."""
    backend = vision_options.get("vision_backend")
    api_key = vision_options.get("vision_api_key")
    if backend and api_key:
        try:
            from app.pipeline.adapters.pdf_adapter import _VISION_MODEL_BY_BACKEND
            from app.services.llm import get_llm_provider

            model_key = _VISION_MODEL_BY_BACKEND.get(backend)
            if model_key:
                provider = get_llm_provider(model_key, api_key=api_key)
                text = provider.generate_vision("", png_bytes, "image/png", _FIGURE_VISION_PROMPT)
                if text and text.strip():
                    return text.strip()
        except Exception:
            logger.exception("figure VLM recognition failed; falling back to Tesseract")
    try:
        import io

        import pytesseract
        from PIL import Image

        from app.pipeline.adapters.pdf_adapter import _TESSERACT_CONFIG, _preprocess_for_ocr

        image = Image.open(io.BytesIO(png_bytes))
        return pytesseract.image_to_string(
            _preprocess_for_ocr(image), lang="kor+eng", config=_TESSERACT_CONFIG
        ).strip()
    except Exception:
        logger.exception("figure Tesseract OCR failed")
        return ""


def _recognize_document_images(document_id: str, parsed, vision_options: dict) -> list[dict]:
    """Filters/dedupes adapter-extracted embedded images, recognizes their
    content (VLM or Tesseract), stores each as PNG in the artifacts bucket,
    and appends "[그림 N] ..." text blocks to the source page so figure content
    flows into chunking/embedding. Returns Document.images records."""
    import hashlib
    import io

    from PIL import Image

    from app.pipeline.adapters.base import RawTextBlock
    from app.services.storage import storage_service

    candidates: list[tuple[object, bytes, str | None]] = []  # (RawPage, png_bytes, native_text)
    seen_hashes: set[str] = set()
    for page in parsed.pages:
        for region in page.image_regions:
            data = region.image_bytes
            if not data or len(data) < _FIGURE_MIN_BYTES:
                continue
            digest = hashlib.sha256(data).hexdigest()
            if digest in seen_hashes:
                continue
            seen_hashes.add(digest)
            try:
                image = Image.open(io.BytesIO(data))
                width, height = image.size
            except Exception:
                logger.debug("이미지 디코드 실패 — 그림 후보에서 제외", exc_info=True,
                             extra={"document_id": document_id})
                continue
            if width < _FIGURE_MIN_DIMENSION or height < _FIGURE_MIN_DIMENSION:
                continue
            buf = io.BytesIO()
            try:
                # Transparent pixels must become white, not black: a bare
                # RGB convert maps alpha to black, which both hurts Tesseract
                # and renders charts on a black card in the 그림 tab.
                if image.mode in ("RGBA", "LA", "P"):
                    rgba = image.convert("RGBA")
                    background = Image.new("RGB", rgba.size, (255, 255, 255))
                    background.paste(rgba, mask=rgba.split()[-1])
                    image = background
                else:
                    image = image.convert("RGB")
                image.save(buf, format="PNG")
            except Exception:
                logger.debug("이미지 PNG 변환 실패 — 그림 후보에서 제외", exc_info=True,
                             extra={"document_id": document_id})
                continue
            candidates.append((page, buf.getvalue(), region.native_text))

    if len(candidates) > _FIGURE_MAX_COUNT:
        logger.info(
            "figure recognition capped",
            extra={"document_id": document_id, "total": len(candidates), "cap": _FIGURE_MAX_COUNT},
        )
        candidates = candidates[:_FIGURE_MAX_COUNT]

    records: list[dict] = []
    for figure_no, (page, png_bytes, native_text) in enumerate(candidates, 1):
        # 그림 안에 원본 텍스트 레이어가 있으면(차트 라벨·수치) 이미지 OCR 보다 정확하므로 그것을 쓴다.
        if native_text and len(native_text.strip()) >= _FIGURE_MIN_MEANINGFUL_CHARS:
            text = native_text.strip()
        else:
            text = _recognize_figure_text(png_bytes, vision_options)
        storage_key = f"images/{document_id}/{figure_no}.png"
        storage_service.upload_file(
            settings.minio_bucket_artifacts, storage_key, png_bytes, "image/png"
        )
        records.append(
            {"page_number": page.page_number, "storage_key": storage_key, "text": text}
        )
        if len(text) >= _FIGURE_MIN_MEANINGFUL_CHARS:
            page.text_blocks.append(
                RawTextBlock(
                    text=f"[그림 {figure_no}]\n{text}",
                    page_number=page.page_number,
                    block_type="image",
                )
            )
    return records


def _clean_rag_text(text: str) -> str:
    """Always-on RAG-side cleaning applied to each chunk before embedding —
    the standing subset of 문서데이터 전처리 방안.md §8.2 (제어문자 제거,
    공백/빈 줄 정규화). Runs on chunk TEXT after span boundaries were
    computed against the raw text, so page attribution offsets stay valid,
    and parsed_text itself is never modified (원본 보존)."""
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    cleaned = "\n".join(
        re.sub(r"[ \t]+", " ", line).strip() for line in cleaned.splitlines()
    )
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _normalize_ws(text: str) -> str:
    return re.sub(r"\s+", "", text)


# How many leading characters of a paragraph/table to use as the match anchor
# against preview-PDF page text. Empirically a SHORT anchor matches far more
# reliably than a long one here: the preview PDF is an HTML reconstruction, so
# a long run of text is more likely to hit a reflow/wrapping difference
# somewhere inside it and fail to match as one contiguous substring, whereas a
# short anchor stays intact even under reflow while still being distinctive
# enough for real business-document text.
_REPAGINATE_ANCHOR_CHARS = 60


def _apply_preview_page_count(document_id: str, doc, parsed) -> None:
    """DOCX 는 파일에 쪽 구분이 없다 — 원문 대조 탭과 같은 LibreOffice 미리보기 PDF(없으면 이때 만들어 캐시)의
    쪽수를 실제 쪽수로 쓴다. PDF 변환이 안 되면(HTML 미리보기로 대체) 아무것도 바꾸지 않는다."""
    from app.services.preview_service import pdf_pages_text_for, preview_url_for

    preview_url_for(document_id, doc.filename, doc.minio_key)
    pages_text = pdf_pages_text_for(document_id)
    if pages_text:
        parsed.page_count = len(pages_text)


def _repaginate_hwp_like(document_id: str, doc, parsed) -> None:
    """HWP/HWPX adapters return everything as a single RawPage numbered 1 —
    these formats have no page boundaries of their own (see hwp_adapter.py).
    This derives real per-page attribution for RAG citations from the same
    LibreOffice-rendered preview PDF already used by the 원문 대조 tab
    (preview_service.py): each paragraph/table text block is located, in
    document order, within that PDF's per-page text. Mutates parsed.pages in
    place. Leaves parsed.pages untouched (still the single page_number=1 page)
    if the preview PDF can't be generated or matched, so citations degrade to
    today's behavior rather than fail the whole parse."""
    from app.pipeline.adapters.base import RawPage
    from app.services.preview_service import pdf_pages_text_for, preview_url_for

    if len(parsed.pages) != 1:
        return

    only_page = parsed.pages[0]
    blocks = [b for b in only_page.text_blocks if b.text.strip()]
    if not blocks:
        return

    try:
        # Also warms the preview cache used by the 원문 대조 tab, so the first
        # user visit to that tab for this document doesn't pay the LibreOffice
        # conversion cost again.
        preview_url_for(document_id, doc.filename, doc.minio_key)
    except Exception:
        logger.exception(
            "HWP/HWPX preview generation failed; RAG citations keep page_number=1",
            extra={"document_id": document_id},
        )
        return

    pages_text = pdf_pages_text_for(document_id)
    if not pages_text:
        return

    normalized_pages = [_normalize_ws(p["text"]) for p in pages_text]

    table_iter = iter(only_page.table_candidates)
    cursor = 0
    unmatched = 0
    assigned: list[tuple] = []  # (block, page_number)
    for block in blocks:
        if block.block_type == "table":
            # block.text is "[표 N]\n{cell | cell | cell}" for display — that
            # header and " | " separator never appear in the PDF's linearized
            # table text, so matching on block.text directly would never hit.
            # Match on the raw cell text instead (order matches table_candidates
            # 1:1 — see hwp_adapter.py's enumerate(table_candidates) loop).
            table = next(table_iter)
            raw_cells = "".join(cell for row in table.rows for cell in row)
            needle = _normalize_ws(raw_cells)[:_REPAGINATE_ANCHOR_CHARS]
        else:
            needle = _normalize_ws(block.text)[:_REPAGINATE_ANCHOR_CHARS]
        found_at = None
        if needle:
            for i in range(cursor, len(normalized_pages)):
                if needle in normalized_pages[i]:
                    found_at = i
                    break
        if found_at is None:
            # No match from the current page onward — likely reconstruction
            # drift (whitespace, a block spanning a page break). Stay on the
            # current page rather than guessing forward or rewinding, so
            # ordering stays monotonic and a bad match can't cascade.
            found_at = cursor
            unmatched += 1
        cursor = found_at
        assigned.append((block, pages_text[found_at]["page_number"]))

    if unmatched:
        logger.info(
            "HWP/HWPX repagination: %d/%d blocks had no direct match in the preview PDF",
            unmatched, len(blocks), extra={"document_id": document_id},
        )

    pages_by_number: dict[int, RawPage] = {}
    for block, page_number in assigned:
        block.page_number = page_number
        page = pages_by_number.get(page_number)
        if page is None:
            page = RawPage(
                page_number=page_number,
                width=only_page.width,
                height=only_page.height,
                text_blocks=[],
                table_candidates=[],
                image_regions=[],
            )
            pages_by_number[page_number] = page
        page.text_blocks.append(block)

    # Each RawTableCandidate has a matching "[표 N]" text block created in the
    # same order in hwp_adapter.py — reuse the page number already resolved
    # for that block rather than re-deriving/re-matching the rendered text.
    table_pages = [page_number for block, page_number in assigned if block.block_type == "table"]
    for table, page_number in zip(only_page.table_candidates, table_pages):
        table.page_number = page_number
        pages_by_number[page_number].table_candidates.append(table)

    # Embedded images aren't repaginated (out of scope here) — attach them to
    # the first real page so they aren't silently dropped from the rebuilt
    # page list.
    if only_page.image_regions:
        first_page_number = next(iter(pages_by_number)) if pages_by_number else 1
        pages_by_number.setdefault(
            first_page_number,
            RawPage(
                page_number=first_page_number,
                width=only_page.width,
                height=only_page.height,
                text_blocks=[],
                table_candidates=[],
                image_regions=[],
            ),
        ).image_regions.extend(only_page.image_regions)

    parsed.pages = [pages_by_number[n] for n in sorted(pages_by_number)]
    # 쪽수는 렌더링된 PDF 의 전체 쪽수 — 텍스트 블록이 없는 쪽(빈 쪽·그림 쪽)도 쪽으로 센다.
    parsed.page_count = len(pages_text)


@celery_app.task(name="tasks.continue_processing", queue="embed", bind=True, max_retries=3)
def continue_processing(self, document_id: str, edited_text: str | None = None) -> dict:
    from app.db.models.document import Document
    from app.db.session import get_sync_db
    from app.pipeline.job_tracker import complete_job, fail_job, start_job
    from app.services.embedding import get_embedding_provider
    from app.services.qdrant_service import qdrant_service

    db = get_sync_db()
    current_job = None
    try:
        doc = db.get(Document, document_id)
        if doc is None:
            return {"document_id": document_id, "status": "NOT_FOUND"}

        if edited_text is not None:
            doc.parsed_text = edited_text
            # page_map was built against the previous text's character offsets;
            # it no longer corresponds to this text, and an edit gives us no
            # reliable way to infer new page boundaries. Clear it so citations
            # show no page number rather than silently pointing at the wrong
            # page — see the caveat in Document.page_map's docstring.
            doc.page_map = None

        embedding_model, chunk_max_tokens, chunk_min_tokens, chunk_overlap_tokens, chunk_strategy = (
            _resolve_collection_settings(db, doc)
        )
        full_text = doc.parsed_text or ""

        current_job = start_job(db, document_id, "CHUNK")
        doc.status = "CHUNKING"
        doc.updated_at = datetime.utcnow()
        db.commit()

        # Semantic chunking needs the embedding model before the CHUNK stage —
        # the provider is resident on this worker, so early init is cheap.
        provider = get_embedding_provider(embedding_model)
        if chunk_strategy == "semantic":
            chunk_spans = _chunk_text_semantic(
                full_text,
                provider,
                max_chars=chunk_max_tokens,
                min_chars=chunk_min_tokens,
            )
        else:
            chunk_spans = _chunk_text(
                full_text,
                max_chars=chunk_max_tokens,
                overlap=chunk_overlap_tokens,
                min_chars=chunk_min_tokens,
            )
        strategy_label_pre = " (의미 기준)" if chunk_strategy == "semantic" else ""
        complete_job(db, current_job, f"{len(chunk_spans)}개 청크 생성{strategy_label_pre}")

        # 정제 단계 (문서데이터 전처리 방안.md §8) — chunk boundaries were
        # computed on the raw text above, so cleaning per-chunk here keeps
        # page_number attribution intact while the RAG store gets clean text.
        current_job = start_job(db, document_id, "NORMALIZE")
        doc.status = "NORMALIZING"
        doc.updated_at = datetime.utcnow()
        db.commit()
        cleaned_spans = []
        dropped_empty = 0
        for text, start, end in chunk_spans:
            cleaned = _clean_rag_text(text)
            if cleaned:
                cleaned_spans.append((cleaned, start, end))
            else:
                dropped_empty += 1
        chunk_spans = cleaned_spans
        complete_job(
            db, current_job,
            f"텍스트 정제 완료 ({dropped_empty}개 빈 청크 제거)" if dropped_empty else "텍스트 정제 완료",
        )

        chunks = [text for text, _start, _end in chunk_spans]
        if not chunks:
            complete_job(db, current_job, "청크 없음 (빈 문서)")
            doc.status = "INDEXED"
            doc.updated_at = datetime.utcnow()
            db.commit()
            # v3 마일스톤 7: 처리 중이던 새 버전이면 지금 현재 버전으로 올리고 이전 버전을 검색에서 뺀다
            from app.services.document_lifecycle import promote_on_indexed_sync

            promote_on_indexed_sync(db, doc)
            from app.pipeline.tasks.summary import generate_summary
            generate_summary.delay(document_id)
            from app.pipeline.tasks.metadata import extract_metadata
            extract_metadata.delay(document_id)
            return {"document_id": document_id, "status": "INDEXED", "chunks": 0}
        current_job = start_job(db, document_id, "EMBED")
        doc.status = "EMBEDDING"
        doc.updated_at = datetime.utcnow()
        db.commit()

        qdrant_service.init_collection(settings.qdrant_collection_name, provider.dimension)

        vectors = provider.embed(chunks)
        complete_job(db, current_job, f"{len(vectors)}개 벡터 생성 ({provider.dimension}차원)")

        from app.services.access_payload import access_payload_sync

        access_fields = access_payload_sync(db, document_id)
        points = [
            {
                "id": str(uuid.uuid4()),
                "vector": vec,
                "payload": {
                    "document_id": document_id,
                    "collection_id": str(doc.collection_id) if doc.collection_id else None,
                    "chunk_index": i,
                    "text": chunk,
                    "filename": doc.original_filename,
                    "page_number": _page_number_for_offset(doc.page_map, start_offset),
                    "tags": doc.tags or [],
                    # v3 권한 사본(sec_rank/acl/owner_id/collection_id) — 정본은 Postgres.
                    **access_fields,
                },
            }
            for i, ((chunk, start_offset, _end_offset), vec) in enumerate(
                zip(chunk_spans, vectors, strict=True)
            )
        ]

        current_job = start_job(db, document_id, "UPLOAD")
        doc.status = "UPLOADING"
        doc.updated_at = datetime.utcnow()
        db.commit()

        # 이전 실행의 벡터는 새 벡터가 준비된 이 시점에야 지운다. 청킹/임베딩 단계에서
        # 실패해도 기존 인덱스가 그대로 남도록 하고, 지우지 않으면 새 UUID로
        # upsert되어 오래된 중복 청크가 함께 검색된다(컬렉션 설정 변경 재처리 등).
        qdrant_service.delete_by_document(settings.qdrant_collection_name, document_id)
        qdrant_service.upsert_points(settings.qdrant_collection_name, points)
        complete_job(db, current_job, f"Qdrant 업로드 완료 ({len(points)}개 포인트)")

        doc.status = "INDEXED"
        doc.updated_at = datetime.utcnow()
        db.commit()
        # v3 마일스톤 7: 처리 중이던 새 버전이면 지금 현재 버전으로 올리고 이전 버전을 검색에서 뺀다
        from app.services.document_lifecycle import promote_on_indexed_sync

        promote_on_indexed_sync(db, doc)

        from app.pipeline.tasks.summary import generate_summary
        generate_summary.delay(document_id)
        from app.pipeline.tasks.metadata import extract_metadata
        extract_metadata.delay(document_id)

        return {"document_id": document_id, "status": "INDEXED", "chunks": len(chunks)}

    except Exception as exc:
        logger.exception(
            "continue_processing failed",
            extra={"document_id": document_id, "retries": self.request.retries},
        )
        db.rollback()
        try:
            if current_job is not None:
                fail_job(db, current_job, str(exc))
            doc = db.get(Document, document_id)
            if doc:
                doc.status = "FAILED"
                doc.error_message = str(exc)[:500]
                doc.updated_at = datetime.utcnow()
                db.commit()
        except Exception:
            logger.exception(
                "continue_processing: failed to record failure state",
                extra={"document_id": document_id},
            )
        raise self.retry(exc=exc, countdown=30)
    finally:
        db.close()
