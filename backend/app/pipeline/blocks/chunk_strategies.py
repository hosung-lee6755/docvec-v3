"""문서 분할(chunk_split) 전략 4종 — 통합 설계서 §3.3⑪.

`fixed`/`semantic`은 여전히 `process.py`의 `_chunk_text`/`_chunk_text_semantic`을
그대로 쓴다(레거시 `continue_processing` 경로와 공유하는 함수라 건드리지 않음).
여기 있는 함수들은 `sentence`/`paragraph`/`section_aware`/`table_unit` 4종만
담당한다.
"""
from dataclasses import dataclass, field

from app.pipeline.tasks.process import _chunk_text, _sentence_spans


@dataclass
class ChunkSpan:
    text: str
    start: int
    end: int
    section_path: list[str] = field(default_factory=list)
    source_node_ids: list[str] = field(default_factory=list)


def _sentence_based_chunks(text: str, max_chars: int, min_chars: int) -> list[ChunkSpan]:
    """문장 경계에서만 자른다 — `_sentence_spans`(이미 `_chunk_text_semantic`이
    쓰는 함수)로 문장 단위를 얻고, `max_chars`까지 그리디하게 채운다. 구조
    분석 트리가 필요 없어 상류에 `structure_analyze`가 없어도 동작한다."""
    spans = _sentence_spans(text)
    if not spans:
        return []
    chunks: list[ChunkSpan] = []
    cur_start, cur_end = spans[0]
    for s, e in spans[1:]:
        if (e - cur_start) > max_chars:
            chunks.append(ChunkSpan(text[cur_start:cur_end], cur_start, cur_end))
            cur_start = s
        cur_end = e
    chunks.append(ChunkSpan(text[cur_start:cur_end], cur_start, cur_end))

    if len(chunks) > 1 and (chunks[-1].end - chunks[-1].start) < min_chars:
        prev, last = chunks[-2], chunks[-1]
        chunks[-2] = ChunkSpan(text[prev.start:last.end], prev.start, last.end)
        chunks.pop()
    return chunks


def _tree_based_chunks(
    nodes: list,
    text: str,
    *,
    max_chars: int,
    min_chars: int,
    respect_headings: bool,
    include_previous_heading: bool,
    preserve_table: bool,
    split_long_paragraph: bool,
    tables_only: bool = False,
) -> list[ChunkSpan]:
    """구조 분석 노드 트리(정렬순 `DocumentNode` 목록)를 훑어 청크를 만든다.
    `paragraph`(respect_headings=False 기본)/`section_aware`(항상 True)/
    `table_unit`(tables_only=True)이 이 함수 하나를 공유한다.

    - `respect_headings`: 제목을 만날 때마다 진행 중인 청크를 닫아 섹션을
      넘어 합치지 않게 한다.
    - `preserve_table`: TABLE 노드는 절대 다른 노드와 섞이지 않고 늘 자기
      혼자만의 청크가 된다.
    - `split_long_paragraph`: 노드 하나가 `max_chars`보다 크면 그 span 안에서
      `_chunk_text`(오버랩 없이)로 하위 분할한다 — false면 크더라도 통째로
      하나의 청크로 유지.
    - `include_previous_heading`: 청크 텍스트 앞에 조상 제목 경로를 프리픽스로
      붙인다. `section_path` 메타데이터 자체는 이 옵션과 무관하게 항상 채운다.
    - `tables_only`: TABLE이 아닌 내용 노드는 건너뛰고 제목 스택만 갱신한다
      (각 표의 section_path 계산용).
    """
    chunks: list[ChunkSpan] = []
    stack: list[tuple[int, str]] = []  # (level, heading_text) — 조상 제목 경로

    buf_node_ids: list[str] = []
    buf_start: int | None = None
    buf_end: int | None = None

    def current_section_path() -> list[str]:
        return [heading_text for _, heading_text in stack]

    def with_prefix(chunk_text: str, section_path: list[str]) -> str:
        if include_previous_heading and section_path:
            return f"[{' > '.join(section_path)}]\n{chunk_text}"
        return chunk_text

    def flush() -> None:
        nonlocal buf_node_ids, buf_start, buf_end
        if not buf_node_ids:
            return
        section_path = current_section_path()
        chunk_text = with_prefix(text[buf_start:buf_end], section_path)
        chunks.append(ChunkSpan(chunk_text, buf_start, buf_end, section_path, list(buf_node_ids)))
        buf_node_ids, buf_start, buf_end = [], None, None

    def append_to_buffer(node) -> None:
        nonlocal buf_start, buf_end
        if not buf_node_ids:
            buf_start = node.span_start
        buf_node_ids.append(str(node.id))
        buf_end = node.span_end

    def split_oversized(node) -> None:
        section_path = current_section_path()
        for sub_text, rel_start, rel_end in _chunk_text(
            text[node.span_start:node.span_end], max_chars=max_chars, overlap=0, min_chars=0
        ):
            start = node.span_start + rel_start
            end = node.span_start + rel_end
            chunks.append(ChunkSpan(with_prefix(sub_text, section_path), start, end, section_path, [str(node.id)]))

    for node in nodes:
        if node.node_type == "DOCUMENT":
            continue  # 루트 노드 — 전체 문서를 뒤덮는 span이라 내용 노드가 아니다

        if node.node_type == "HEADING":
            if respect_headings:
                flush()
            level = node.level if node.level is not None else 1
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, node.text or ""))
            continue

        if node.span_start is None or node.span_end is None:
            continue  # 방어적 — TABLE을 포함한 모든 내용 노드 타입은 span을 가져야 함

        is_table = node.node_type == "TABLE"
        if tables_only and not is_table:
            continue

        node_len = node.span_end - node.span_start

        if is_table and preserve_table:
            flush()
            if node_len > max_chars and split_long_paragraph:
                split_oversized(node)
            else:
                append_to_buffer(node)
                flush()
            continue

        would_overflow = bool(buf_node_ids) and (buf_end - buf_start) + node_len > max_chars
        if would_overflow:
            flush()

        if node_len > max_chars and split_long_paragraph:
            flush()
            split_oversized(node)
            continue

        append_to_buffer(node)

    flush()

    # 꼬리 병합: 마지막 청크가 min_chars 미만이면 직전 청크에 합친다 — 단,
    # 같은 section_path일 때만(다른 섹션과는 절대 섞지 않는다).
    if len(chunks) > 1 and (chunks[-1].end - chunks[-1].start) < min_chars:
        prev, last = chunks[-2], chunks[-1]
        if prev.section_path == last.section_path:
            merged_text = with_prefix(text[prev.start:last.end], prev.section_path)
            chunks[-2] = ChunkSpan(
                merged_text, prev.start, last.end, prev.section_path,
                prev.source_node_ids + last.source_node_ids,
            )
            chunks.pop()

    return chunks
