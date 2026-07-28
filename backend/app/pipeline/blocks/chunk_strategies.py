"""문서 분할(chunk_split) 전략 4종 — 통합 설계서 §3.3⑪.

`fixed`/`semantic`은 여전히 `process.py`의 `_chunk_text`/`_chunk_text_semantic`을
그대로 쓴다(레거시 `continue_processing` 경로와 공유하는 함수라 건드리지 않음).
여기 있는 함수들은 `sentence`/`paragraph`/`section_aware`/`table_unit` 4종만
담당한다.
"""
import re
from dataclasses import dataclass, field

from app.pipeline.blocks.table_markdown import rows_to_markdown
from app.pipeline.tasks.process import _chunk_text, _sentence_spans

_HANGUL_TOKEN_RE = re.compile(r"[가-힣]")


def _estimate_token_count(text: str) -> int:
    """정밀 토크나이저 없이 청크의 토큰 수를 저비용으로 근사한다(메타 정보
    생성 설계서, 2026-07-23 Phase 4) — 한글은 음절 하나가 대체로 토큰 하나에
    가깝고, 그 외 문자(영문/숫자/기호)는 대략 4글자당 토큰 하나로 어림한다.
    BGE-M3 등 실제 서브워드 토크나이저와 정확히 일치하지 않지만, 청크 크기
    감각을 보여주는 용도로는 충분하다."""
    if not text:
        return 0
    hangul_chars = len(_HANGUL_TOKEN_RE.findall(text))
    other_chars = len(text) - hangul_chars
    return max(1, hangul_chars + other_chars // 4)


# Chunk 계층형 Parent Retrieval(메타 정보 생성.txt 3절, Phase 9, 사용자 확정
# 2026-07-24) — 조상 헤딩이 없는 flat 구간(fixed/semantic/sentence 전략,
# 또는 구조 없는 문서)에서 연속 child를 몇 개씩 하나의 parent로 묶을지.
_PARENT_GROUP_MAX_CHILDREN = 5
# parent 하나의 combined 길이가 child 목표 크기(max_chars)의 몇 배를 넘으면
# 그 자리에서 그룹을 끊을지 — 너무 큰 parent가 만들어지는 것을 방지.
_PARENT_SIZE_MULTIPLIER = 4


def group_children_into_parents(
    spans: list[tuple],
    max_chars: int,
) -> list[list[int]]:
    """`spans`는 (cleaned, raw, start, end, section_path, source_node_ids) 6-tuple
    목록(storage_blocks.py::ChunkSplitBlock.run()의 cleaned_spans와 동일한 shape,
    4개 청킹 전략 전부 이 shape로 통일되어 있음). 같은 section_path를 공유하는
    연속 child들을 하나의 parent 그룹으로 묶어 그 인덱스 목록을 돌려준다.
    section_path가 항상 빈 리스트인 전략(fixed/semantic/sentence)은 헤딩 정보가
    없으므로 `_PARENT_GROUP_MAX_CHILDREN`개씩 묶는 것으로 폴백한다."""
    groups: list[list[int]] = []
    current: list[int] = []
    current_section: list[str] | None = None
    group_start: int | None = None

    def flush() -> None:
        if current:
            groups.append(list(current))

    for i, span in enumerate(spans):
        _cleaned, _raw, start, end, section_path, _node_ids = span
        section_changed = bool(current) and section_path != current_section
        flat_group_full = (
            bool(current) and not section_path and len(current) >= _PARENT_GROUP_MAX_CHILDREN
        )
        too_big = (
            bool(current) and group_start is not None
            and (end - group_start) > max_chars * _PARENT_SIZE_MULTIPLIER
        )
        if section_changed or flat_group_full or too_big:
            flush()
            current = []
            group_start = None
        if not current:
            group_start = start
        current.append(i)
        current_section = section_path
    flush()
    return groups


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


def _table_rows_and_ordinal(
    source_table_id: str | None, tables: list[dict] | None,
) -> tuple[list[list[str]] | None, int | None]:
    """`Document.tables`에서 `source_table_id`가 가리키는 원본 행 데이터를
    찾는다. `tables`의 인덱스+1을 표 번호(ordinal)로 함께 돌려줘 청크 텍스트에
    "[표 N] (부분 M/K)"로 추적 가능하게 표시할 수 있게 한다(문서 파싱 고도화
    Phase 3, 사용자가 제안한 행 단위 청킹)."""
    if not tables or not source_table_id:
        return None, None
    for i, t in enumerate(tables):
        if t.get("id") == source_table_id:
            return t.get("rows"), i + 1
    return None, None


def _split_table_rows(
    rows: list[list[str]],
    ordinal: int | None,
    max_chars: int,
    max_rows: int | None,
) -> list[str]:
    """첫 행(헤더)을 고정하고 나머지 행을 그룹화해 각 그룹을 헤더 반복 포함
    markdown으로 렌더링한다. `max_rows`가 주어지면 그 행 수 기준, 없으면
    `max_chars`(헤더 포함 렌더링 결과 길이) 기준 그리디 그룹화 — 사용자가
    제안한 "매 청크마다 헤더를 함께 포함"을 그대로 구현한다."""
    if not rows:
        return []
    header, body = rows[0], rows[1:]
    if not body:
        return [rows_to_markdown(rows)]

    groups: list[list[list[str]]] = []
    if max_rows:
        for i in range(0, len(body), max_rows):
            groups.append(body[i:i + max_rows])
    else:
        current: list[list[str]] = []
        for row in body:
            candidate = current + [row]
            if current and len(rows_to_markdown([header, *candidate])) > max_chars:
                groups.append(current)
                current = [row]
            else:
                current = candidate
        if current:
            groups.append(current)

    total = len(groups)
    rendered = []
    for i, group in enumerate(groups, start=1):
        md = rows_to_markdown([header, *group])
        label = f"[표 {ordinal}] " if ordinal else ""
        rendered.append(f"{label}(부분 {i}/{total})\n{md}")
    return rendered


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
    tables: list[dict] | None = None,
    table_chunk_max_rows: int | None = None,
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
    - `tables`/`table_chunk_max_rows`: 오버사이즈 TABLE 노드 전용 분기(문서
      파싱 고도화 Phase 3) — `tables`(`Document.tables`)로 원본 행 데이터를
      찾을 수 있으면 문자수 컷 대신 첫 행(헤더)을 반복 포함하는 행 그룹으로
      나눈다(표 의미가 중간에 끊겨 사라지지 않도록). `tables`가 없거나 해당
      노드의 `source_table_id`로 행을 못 찾으면 기존 문자수 컷으로 폴백.
    """
    chunks: list[ChunkSpan] = []
    stack: list[tuple[int, str]] = []  # (level, heading_text) — 조상 제목 경로
    table_node_ids = {str(n.id) for n in nodes if getattr(n, "node_type", None) == "TABLE"}

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

        if node.node_type == "TABLE":
            rows, ordinal = _table_rows_and_ordinal(getattr(node, "source_table_id", None), tables)
            if rows:
                # 행 그룹 렌더링은 원본 markdown의 부분 문자열이 아니다(헤더가
                # 반복 삽입되므로) — 따라서 각 조각의 span은 원본 TABLE 노드
                # 전체 span을 그대로 공유한다(어느 조각이든 원문 출처는 이
                # 표 전체이므로 정확함).
                for part_text in _split_table_rows(rows, ordinal, max_chars, table_chunk_max_rows):
                    chunks.append(ChunkSpan(
                        with_prefix(part_text, section_path),
                        node.span_start, node.span_end, section_path, [str(node.id)],
                    ))
                return
            # rows를 못 찾음(방어적 폴백, 예: source_table_id 없음/오래된 문서)
            # — 기존 문자수 컷으로 진행.

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
    # 같은 section_path일 때만(다른 섹션과는 절대 섞지 않는다), 그리고 둘 중
    # 하나라도 TABLE 노드에서 온 청크면 절대 합치지 않는다 — preserve_table의
    # "표는 항상 자기 혼자만의 청크" 보장이 꼬리 병합으로 깨지는 것을 방지
    # (문서 파싱 고도화 회고, 2026-07-23).
    if len(chunks) > 1 and (chunks[-1].end - chunks[-1].start) < min_chars:
        prev, last = chunks[-2], chunks[-1]
        prev_or_last_is_table = bool(
            table_node_ids.intersection(prev.source_node_ids)
            or table_node_ids.intersection(last.source_node_ids)
        )
        if prev.section_path == last.section_path and not prev_or_last_is_table:
            merged_text = with_prefix(text[prev.start:last.end], prev.section_path)
            chunks[-2] = ChunkSpan(
                merged_text, prev.start, last.end, prev.section_path,
                prev.source_node_ids + last.source_node_ids,
            )
            chunks.pop()

    return chunks
