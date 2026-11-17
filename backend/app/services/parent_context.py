"""Parent Retrieval: 검색은 작은 청크(child)로 정확하게 찾고, 답변 생성 때는 그 청크가 속한
상위 절(parent)의 앞뒤 청크를 함께 LLM에 넘긴다(2026-11-13).

예전에는 parent 행을 만들어 청크 탭에 보여 주기만 하고 채팅 문맥에는 쓰지 않았다.
문맥은 parent 행의 본문(원문 구간 그대로)이 아니라, 같은 parent에 속한 child 가운데 지금
검색에 쓰이는 것(벡터 DB에 있고 '검색 제외'가 아닌 것)의 본문을 이어 붙여 만든다. 그래야
청크 수정, 검색 제외, 민감정보 제외가 답변 문맥에도 그대로 지켜진다.
"""
import logging

logger = logging.getLogger(__name__)

# 근거 하나에 넣는 문맥의 최대 글자 수. 근거 10건이어도 Ollama 문맥(16,384토큰) 안에 들어간다
PARENT_CONTEXT_MAX_CHARS = 1200


def expand_window(texts: list[str], hit: int, max_chars: int, skip: set[int] | None = None) -> list[int]:
    """hit 청크를 중심으로 앞뒤 청크를 번갈아 붙여, 합친 길이가 max_chars를 넘지 않는 연속 구간의
    인덱스를 순서대로 돌려준다. hit 자체는 길이와 상관없이 항상 들어간다. 한쪽 방향은 길이를 넘거나
    skip(앞선 근거의 문맥에 이미 들어간 청크)을 만나면 거기서 멈춰, 문맥이 중간에 끊기지 않는다."""
    skip = skip or set()
    lo = hi = hit
    total = len(texts[hit])
    left_open = right_open = True
    while left_open or right_open:
        if left_open:
            idx = lo - 1
            if idx < 0 or idx in skip or total + len(texts[idx]) > max_chars:
                left_open = False
            else:
                lo, total = idx, total + len(texts[idx])
        if right_open:
            idx = hi + 1
            if idx >= len(texts) or idx in skip or total + len(texts[idx]) > max_chars:
                right_open = False
            else:
                hi, total = idx, total + len(texts[idx])
    return list(range(lo, hi + 1))


def _sibling_rows(db, chunk_ids: list[str]) -> tuple[dict[str, str], dict[str, list[str]]]:
    """검색된 청크 id → parent id, parent id → 순서대로 정렬한 child id 목록."""
    from app.db.models.document_chunk import DocumentChunk

    rows = db.query(DocumentChunk.id, DocumentChunk.parent_chunk_id).filter(
        DocumentChunk.id.in_(chunk_ids)
    ).all()
    parent_of = {str(cid): str(pid) for cid, pid in rows if pid}
    if not parent_of:
        return {}, {}
    siblings = db.query(DocumentChunk.id, DocumentChunk.parent_chunk_id).filter(
        DocumentChunk.parent_chunk_id.in_(set(parent_of.values())),
        DocumentChunk.chunk_tier == "child",
    ).order_by(DocumentChunk.chunk_order).all()
    children: dict[str, list[str]] = {}
    for cid, pid in siblings:
        children.setdefault(str(pid), []).append(str(cid))
    return parent_of, children


def _searchable_texts(point_ids: list[str]) -> dict[str, str]:
    """벡터 DB에 있고 검색 제외가 아닌 청크의 현재 본문."""
    from app.core.config import settings
    from app.services.qdrant_service import qdrant_service

    points = qdrant_service.get_points(settings.qdrant_collection_name, point_ids)
    return {
        p["id"]: p["payload"].get("text", "")
        for p in points
        if not p["payload"].get("disabled") and p["payload"].get("text")
    }


def attach_parent_context(db, chunks: list[dict], max_chars: int = PARENT_CONTEXT_MAX_CHARS) -> list[dict]:
    """각 근거에 'context_text'를 붙인 새 목록을 돌려준다. 인용(text)은 그대로 child 본문이다.
    문맥을 만들지 못하면 근거를 그대로 돌려준다(답변은 child 본문만으로 계속된다)."""
    refs = [c["chunk_ref"] for c in chunks if c.get("source_kind") == "chunk" and c.get("chunk_ref")]
    if not refs:
        return chunks
    try:
        parent_of, children = _sibling_rows(db, refs)
        all_ids = sorted({cid for ids in children.values() for cid in ids})
        texts_by_id = _searchable_texts(all_ids) if all_ids else {}
    except Exception:  # noqa: BLE001
        logger.exception("parent context lookup failed; answering with child chunks only")
        return chunks

    used: set[str] = set()
    expanded: list[dict] = []
    for chunk in chunks:
        ref = chunk.get("chunk_ref")
        if chunk.get("source_kind") != "chunk" or not ref:
            expanded.append(chunk)
            continue
        siblings = [cid for cid in children.get(parent_of.get(ref, ""), []) if cid in texts_by_id or cid == ref]
        if ref not in siblings or len(siblings) < 2:
            used.add(ref)
            expanded.append(chunk)
            continue
        # 검색된 청크는 근거 목록의 본문(text)을 그대로 쓴다(인용과 문맥이 어긋나지 않게)
        texts = [chunk["text"] if cid == ref else texts_by_id[cid] for cid in siblings]
        skip = {i for i, cid in enumerate(siblings) if cid in used}
        window = expand_window(texts, siblings.index(ref), max_chars, skip)
        used.update(siblings[i] for i in window)
        if len(window) == 1:
            expanded.append(chunk)
            continue
        expanded.append({**chunk, "context_text": "\n".join(texts[i] for i in window)})
    return expanded
