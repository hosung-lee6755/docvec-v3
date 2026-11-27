"""문서 분할(chunk_split) 전략 4종 — 통합 설계서 §3.3⑪.

`fixed`/`semantic`은 여전히 `process.py`의 `_chunk_text`/`_chunk_text_semantic`을
그대로 쓴다(레거시 `continue_processing` 경로와 공유하는 함수라 건드리지 않음).
여기 있는 함수들은 `sentence`/`paragraph`/`section_aware`/`table_unit` 4종만
담당한다.
"""
import re
from dataclasses import dataclass, field

from app.pipeline.blocks.table_markdown import rows_to_markdown
from app.pipeline.tasks.process import _chunk_text, _last_sentence_end, _sentence_spans

_HANGUL_TOKEN_RE = re.compile(r"[가-힣]")

# 쪽이나 단이 넘어가며 한 문장이 두 노드로 나뉜 경우(Pub120 "... with all procedures specified" /
# "in the vessel security plan ...", 2026-11-23). 앞 글이 문장 끝 없이 끝나고 다음 노드가 영문 소문자로
# 시작하면 이어지는 문장으로 본다. "b. Southern ..." 같은 목록 기호와 주소는 새 항목이다
_OPEN_END_RE = re.compile(r"[^.!?。！？:;)\]\"'”’\s]\s*$")
_CONTINUATION_START_RE = re.compile(r"\s*[a-z]")
_NEW_ITEM_START_RE = re.compile(r"\s*(?:[a-z]{1,2}\.\s|https?:|www\.)")
_SENTENCE_CLOSED_RE = re.compile(r"[.!?。！？:;)\]\"'”’]\s*$")
_END_WINDOW = 12


def _continues_sentence(text: str, buf_end: int | None, node) -> bool:
    if buf_end is None or node.span_start is None:
        return False
    head = text[node.span_start:node.span_start + 40]
    tail = text[max(0, buf_end - 40):buf_end]
    # 띄어쓰기가 있는 글(문장)끼리만 잇는다. 코드·기호 덩어리는 문장이 아니다
    if " " not in head.strip() or " " not in tail.strip():
        return False
    return (
        bool(_OPEN_END_RE.search(text, max(0, buf_end - _END_WINDOW), buf_end))
        and bool(_CONTINUATION_START_RE.match(head))
        and not _NEW_ITEM_START_RE.match(head)
    )


def _estimate_token_count(text: str) -> int:
    """정밀 토크나이저 없이 청크의 토큰 수를 저비용으로 근사한다 — 한글은 음절
    하나가 대체로 토큰 하나에 가깝고, 그 외 문자(영문/숫자/기호)는 대략 4글자당
    토큰 하나로 어림한다. BGE-M3 등 실제 서브워드 토크나이저와 정확히 일치하지
    않지만, 청크 크기 감각을 보여주는 용도로는 충분하다."""
    if not text:
        return 0
    hangul_chars = len(_HANGUL_TOKEN_RE.findall(text))
    other_chars = len(text) - hangul_chars
    return max(1, hangul_chars + other_chars // 4)


# Chunk 계층형 Parent Retrieval(메타 정보 생성.txt 3절, Phase 9) — 조상 헤딩이 없는
# flat 구간(fixed/semantic/sentence 전략,
# 또는 구조 없는 문서)에서 연속 child를 몇 개씩 하나의 parent로 묶을지.
_PARENT_GROUP_MAX_CHILDREN = 5
# 청크 본문에 넣지 않는 구조 노드(structure_refine.py가 쪽 가장자리 반복 문구와 목차 줄을 이렇게 표시한다)
_NON_BODY_NODE_TYPES = {"HEADER", "FOOTER", "TOC"}
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
    group_root: list[str] | None = None
    group_start: int | None = None

    def flush() -> None:
        if current:
            groups.append(list(current))

    for i, span in enumerate(spans):
        _cleaned, _raw, start, end, section_path, _node_ids = span
        # 예전에는 section_path가 완전히 같은 child만 묶어, 세부 절이 많은 문서에서는 parent가
        # child와 1:1이 되어 상위 문맥이 생기지 않았다(2026-11-13 측정). 이제 같은 상위 절에
        # 속한 연속 child를 묶는다. 묶음의 첫 child가 정한 상위 절 경로로 시작하면 같은 묶음이다.
        section_changed = bool(current) and not _within_root(section_path, group_root)
        flat_group_full = (
            bool(current) and not section_path and len(current) >= _PARENT_GROUP_MAX_CHILDREN
        )
        too_big = (
            bool(current) and group_start is not None
            and (end - group_start) > max_chars * _PARENT_SIZE_MULTIPLIER
        )
        # 큰 표를 행 묶음으로 나눈 조각은 모두 표 전체 범위를 공유한다. 앞 조각과 범위가 같으면 같은 parent 에 둔다.
        # 예전에는 조각마다 표 전체를 담은 parent 가 따로 생겼다(2026-11-20 감사)
        same_span_as_previous = bool(current) and spans[current[-1]][2:4] == (start, end)
        if (section_changed or flat_group_full or too_big) and not same_span_as_previous:
            flush()
            current = []
            group_start = None
        if not current:
            group_start = start
            group_root = _parent_root(section_path)
        current.append(i)
    flush()
    return groups


def non_body_ranges(nodes: list) -> list[tuple[int, int]]:
    """청크 본문에서 뺄 머리말·꼬리말·목차 노드의 위치(시작 순)."""
    return sorted(
        (n.span_start, n.span_end)
        for n in nodes
        if getattr(n, "node_type", None) in _NON_BODY_NODE_TYPES
        and n.span_start is not None and n.span_end is not None and n.span_end > n.span_start
    )


def strip_ranges(chunk_text: str, full_text: str, start: int, end: int, ranges: list[tuple[int, int]]) -> str:
    """청크는 원문을 연속 구간으로 자르므로, 구간 가운데의 쪽 꼬리말이나 목차 줄이 그대로 따라 들어온다
    (2026-11-13). 청크 본문(full_text[start:end]) 안에 있는 ranges 부분을 지운 글을 돌려준다.
    위치(start, end)는 그대로라 쪽 번호와 원문 대조에는 영향이 없다. 본문이 원문 구간과 다르면
    (표를 행 단위로 다시 쓴 청크 등) 손대지 않는다. 앞에 붙은 절 경로 머리말은 유지한다."""
    import bisect

    first = max(0, bisect.bisect_left(ranges, (start, -1)) - 1)
    cuts = [(max(s, start), min(e, end)) for s, e in ranges[first:] if s < end and e > start]
    body = full_text[start:end]
    if not cuts or not chunk_text.endswith(body):
        return chunk_text
    prefix = chunk_text[: len(chunk_text) - len(body)]
    pieces, pos = [], start
    for cut_start, cut_end in cuts:
        if cut_start > pos:
            pieces.append(full_text[pos:cut_start])
        pos = max(pos, cut_end)
    pieces.append(full_text[pos:end])
    return prefix + "".join(pieces)


def _parent_root(section_path: list[str] | None) -> list[str]:
    """parent 묶음의 기준 경로. 절 경로가 둘 이상이면 바로 위 절이고, 하나면 그 절 자체다."""
    path = list(section_path or [])
    return path[:-1] if len(path) > 1 else path


def _within_root(section_path: list[str] | None, root: list[str] | None) -> bool:
    path = list(section_path or [])
    if not root:
        # 경로가 없는 구간끼리만 묶는다(개수 상한은 호출부의 flat_group_full이 정한다)
        return not path
    return path[: len(root)] == root


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
    Phase 3)."""
    if not tables or not source_table_id:
        return None, None
    for i, t in enumerate(tables):
        if t.get("id") == source_table_id:
            return t.get("rows"), i + 1
    return None, None


def mask_table_cells(tables: list[dict] | None, replacements: list[tuple[str, str]]) -> list[dict] | None:
    """표 칸에 글과 같은 민감정보 가리기를 적용한 새 표 목록. 큰 표 조각은 Document.tables 의 칸으로 만들어,
    예전에는 가리기로 한 전화번호와 이메일이 검색 청크에 그대로 들어갔다(2026-11-20 감사). 원본 표는 그대로 둔다."""
    if not tables or not replacements:
        return tables
    ordered = sorted(replacements, key=lambda pair: len(pair[0]), reverse=True)

    def mask(cell):
        if not isinstance(cell, str):
            return cell
        for original, masked in ordered:
            if original and original in cell:
                cell = cell.replace(original, masked)
        return cell

    masked_tables = []
    for table in tables:
        rows = table.get("rows") if isinstance(table, dict) else None
        if not rows:
            masked_tables.append(table)
            continue
        masked_tables.append({**table, "rows": [[mask(cell) for cell in row] for row in rows]})
    return masked_tables


def _table_title(source_table_id: str | None, tables: list[dict] | None) -> str | None:
    """`Document.tables`에 남은 표 제목(캡션이나 맨 위 제목 줄). 없으면 None."""
    for table in tables or []:
        if source_table_id and table.get("id") == source_table_id:
            return table.get("title") or None
    return None


# 머리 행과 첫 열만으로 예산을 거의 다 쓰는 표에서도 셀 글을 담을 최소 자리
_MIN_ROW_TEXT_BUDGET = 100
# 나뉜 행마다 되풀이할 행 이름(첫 열)의 최대 길이. 이보다 길면 이름이 아니라 내용이다
_MAX_ROW_LABEL_CHARS = 100


def _row_segments(text: str, budget: int) -> list[str]:
    """셀 글을 문장 단위로 자르고, 문장 하나가 예산보다 길면 글자 수로 자른다."""
    sentences = [text[s:e].strip() for s, e in _sentence_spans(text)] or [text]
    pieces: list[str] = []
    for sentence in sentences:
        pieces.extend(sentence[i:i + budget] for i in range(0, len(sentence), budget))
    return [p for p in pieces if p]


def _split_long_row(header: list[str], row: list[str], max_chars: int) -> list[list[str]]:
    """머리 행과 함께 렌더링했을 때 `max_chars`를 넘는 행을 여러 행으로 나눈다.

    나뉜 행마다 첫 열(행 이름)을 그대로 두어 어느 행의 이어지는 글인지 알 수 있게 한다.
    나머지 열의 글은 순서대로 문장 단위로 채우고, 넘치면 다음 행으로 넘긴다.
    """
    width = max(len(header), len(row))
    padded = list(row) + [""] * (width - len(row))
    if len(rows_to_markdown([header, padded])) <= max_chars or width < 2:
        return [list(row)]

    label = padded[0]
    # 첫 열이 행 이름이 아니라 가로로 합친 긴 설명이면(고도화보고서 "왜 바꿨나 …" 행) 그 글도 나눠 담는다.
    # 예전에는 첫 열을 되풀이할 이름으로만 봐서, 나머지 열이 빈 설명 행을 통째로 버렸다(2026-11-20 감사)
    first_col = 1
    if len(label) > _MAX_ROW_LABEL_CHARS:
        label, first_col = "", 0
    empty = [label] + [""] * (width - 1)
    budget = max(max_chars - len(rows_to_markdown([header, empty])), _MIN_ROW_TEXT_BUDGET)
    pieces: list[list[str]] = []
    current = empty
    for col in range(first_col, width):
        for segment in _row_segments(padded[col], budget):
            joined = f"{current[col]} {segment}" if current[col] else segment
            candidate = [*current[:col], joined, *current[col + 1:]]
            if current != empty and len(rows_to_markdown([header, candidate])) > max_chars:
                pieces.append(current)
                candidate = [*empty[:col], segment, *empty[col + 1:]]
            current = candidate
    if current != empty:
        pieces.append(current)
    return pieces


def _split_table_rows(
    rows: list[list[str]],
    ordinal: int | None,
    max_chars: int,
    max_rows: int | None,
    title: str | None = None,
) -> list[str]:
    """첫 행(헤더)을 고정하고 나머지 행을 그룹화해 각 그룹을 헤더 반복 포함
    markdown으로 렌더링한다. `max_rows`가 주어지면 그 행 수 기준, 없으면
    `max_chars`(헤더 포함 렌더링 결과 길이) 기준 그리디 그룹화 — 사용자가
    제안한 "매 청크마다 헤더를 함께 포함"을 그대로 구현한다.

    표 제목이 있으면 조각마다 "[표 N] 제목 (부분 i/k)"로 붙인다. 둘째 조각부터는 제목이 없어
    표 주제로 검색해도 잡히지 않았다(2026-11-17 표 검색 점검)."""
    if not rows:
        return []
    header, body = rows[0], rows[1:]
    if not body:
        return [rows_to_markdown(rows)]
    # 행 하나가 예산보다 길면 행 단위로는 더 나눌 수 없어 큰 청크가 남는다. 그런 행은 미리
    # 셀 글을 문장 경계에서 여러 행으로 나눠 둔다
    body = [piece for row in body for piece in _split_long_row(header, row, max_chars)]

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
        if title:
            label = f"{label}{title} "
        rendered.append(f"{label}(부분 {i}/{total})\n{md}")
    return rendered


def _only_open_headings(buf_node_ids: list[str], heading_ids: set[str], body_less: set[str]) -> bool:
    """버퍼가 본문을 가진 제목(구획 경로에 남는 제목)으로만 차 있는지. 본문 없는 제목은 문단처럼 담으므로 빼지 않는다."""
    return bool(buf_node_ids) and all(i in heading_ids and i not in body_less for i in buf_node_ids)


def _headings_without_body(nodes: list) -> set[str]:
    """아래에 본문(표 포함) 없이 같은 수준 이상의 제목이나 문서 끝이 바로 오는 제목의 id.
    한 줄짜리 조문("제4조(효력기간) 본 협정서는 …")이나 제목으로 분류된 번호 줄이 여기에 든다(2026-11-20 감사)."""
    body_less: set[str] = set()
    open_headings: list[tuple[int, str]] = []
    for node in nodes:
        node_type = getattr(node, "node_type", None)
        if node_type == "DOCUMENT" or node_type in _NON_BODY_NODE_TYPES:
            continue
        if node_type == "HEADING":
            level = node.level if node.level is not None else 1
            while open_headings and open_headings[-1][0] >= level:
                body_less.add(open_headings.pop()[1])
            open_headings.append((level, str(node.id)))
            continue
        if node.span_start is not None and node.span_end is not None:
            open_headings.clear()
    body_less.update(node_id for _level, node_id in open_headings)
    return body_less


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
    merge_small_sections: bool = False,
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
    heading_node_ids = {str(n.id) for n in nodes if getattr(n, "node_type", None) == "HEADING"}
    body_less_headings = _headings_without_body(nodes)

    buf_node_ids: list[str] = []
    buf_spans: list[tuple[str, int, int]] = []  # 버퍼에 든 노드별 (id, 시작, 끝) — 문장 이어 담기에서 나눌 때 쓴다
    buf_start: int | None = None
    buf_end: int | None = None
    # 큰 문단을 나눈 마지막 조각이 문장 중간에서 끝나 다음 노드를 기다리는 중인지
    open_tail = False

    def current_section_path() -> list[str]:
        return [heading_text for _, heading_text in stack]

    def with_prefix(chunk_text: str, section_path: list[str]) -> str:
        if include_previous_heading and section_path:
            return f"[{' > '.join(section_path)}]\n{chunk_text}"
        return chunk_text

    def flush() -> None:
        nonlocal buf_node_ids, buf_spans, buf_start, buf_end, open_tail
        open_tail = False
        if not buf_node_ids:
            return
        section_path = current_section_path()
        chunk_text = with_prefix(text[buf_start:buf_end], section_path)
        chunks.append(ChunkSpan(chunk_text, buf_start, buf_end, section_path, list(buf_node_ids)))
        buf_node_ids, buf_spans, buf_start, buf_end = [], [], None, None

    def set_buffer(spans: list[tuple[str, int, int]]) -> None:
        nonlocal buf_node_ids, buf_spans, buf_start, buf_end
        buf_spans = list(spans)
        buf_node_ids = list(dict.fromkeys(node_id for node_id, _s, _e in spans))
        buf_start, buf_end = (spans[0][1], spans[-1][2]) if spans else (None, None)

    def append_to_buffer(node) -> None:
        set_buffer([*buf_spans, (str(node.id), node.span_start, node.span_end)])

    def carry_open_sentence() -> None:
        """버퍼를 마지막 문장 끝에서 닫고, 끝나지 않은 문장은 버퍼에 남겨 다음 노드와 잇는다."""
        cut = _last_sentence_end(text, buf_start, buf_end)
        if cut is None or cut <= buf_start or cut >= buf_end:
            return
        section_path = current_section_path()
        head = [(i, s, min(e, cut)) for i, s, e in buf_spans if s < cut]
        tail = [(i, max(s, cut), e) for i, s, e in buf_spans if e > cut]
        chunks.append(ChunkSpan(
            with_prefix(text[buf_start:cut], section_path), buf_start, cut, section_path,
            list(dict.fromkeys(i for i, _s, _e in head)),
        ))
        set_buffer(tail)

    def split_range(spans: list[tuple[str, int, int]]) -> None:
        """여러 노드에 걸친 구간을 `_chunk_text`로 나눈다. 마지막 조각이 문장 중간에서 끝나면 버퍼에 남긴다."""
        nonlocal open_tail
        start, end = spans[0][1], spans[-1][2]
        node_ids = list(dict.fromkeys(i for i, _s, _e in spans))
        section_path = current_section_path()
        pieces = _chunk_text(text[start:end], max_chars=max_chars, overlap=0, min_chars=0)
        for index, (sub_text, rel_start, rel_end) in enumerate(pieces):
            piece_start, piece_end = start + rel_start, start + rel_end
            is_last = index == len(pieces) - 1
            if is_last and not _SENTENCE_CLOSED_RE.search(text, max(start, piece_end - _END_WINDOW), piece_end):
                set_buffer([(node_ids[-1], piece_start, piece_end)])
                open_tail = True
                return
            chunks.append(ChunkSpan(with_prefix(sub_text, section_path), piece_start, piece_end, section_path, node_ids))

    def split_oversized(node) -> None:
        section_path = current_section_path()

        if node.node_type == "TABLE":
            rows, ordinal = _table_rows_and_ordinal(getattr(node, "source_table_id", None), tables)
            if rows:
                # 행 그룹 렌더링은 원본 markdown의 부분 문자열이 아니다(헤더가
                # 반복 삽입되므로) — 따라서 각 조각의 span은 원본 TABLE 노드
                # 전체 span을 그대로 공유한다(어느 조각이든 원문 출처는 이
                # 표 전체이므로 정확함).
                title = _table_title(getattr(node, "source_table_id", None), tables)
                for part_text in _split_table_rows(rows, ordinal, max_chars, table_chunk_max_rows, title):
                    chunks.append(ChunkSpan(
                        with_prefix(part_text, section_path),
                        node.span_start, node.span_end, section_path, [str(node.id)],
                    ))
                return
            # rows를 못 찾음(방어적 폴백, 예: source_table_id 없음/오래된 문서)
            # — 기존 문자수 컷으로 진행.

        if node.node_type == "TABLE":
            # 표는 늘 자기 혼자만의 청크다(preserve_table). 다음 노드와 잇지 않는다
            for sub_text, rel_start, rel_end in _chunk_text(
                text[node.span_start:node.span_end], max_chars=max_chars, overlap=0, min_chars=0
            ):
                start = node.span_start + rel_start
                end = node.span_start + rel_end
                chunks.append(ChunkSpan(with_prefix(sub_text, section_path), start, end, section_path, [str(node.id)]))
            return
        split_range([(str(node.id), node.span_start, node.span_end)])

    for node in nodes:
        if node.node_type == "DOCUMENT":
            continue  # 루트 노드 — 전체 문서를 뒤덮는 span이라 내용 노드가 아니다
        if node.node_type in _NON_BODY_NODE_TYPES:
            continue  # 쪽마다 반복되는 머리말·꼬리말과 목차 줄은 검색 근거로 쓰지 않는다(2026-11-13)

        if node.node_type == "HEADING":
            if respect_headings and _only_open_headings(buf_node_ids, heading_node_ids, body_less_headings):
                # 버퍼에 본문 있는 제목만 있고 바로 하위 제목이 오면, 그 제목은 뒤 청크들의 구획 경로에 들어간다.
                # 제목 한 줄짜리 청크("제2장 복무")를 따로 만들면 검색 후보만 차지해 정답 조문을 밀어냈다(2026-11-27)
                set_buffer([])
                open_tail = False
            elif respect_headings:
                flush()
            level = node.level if node.level is not None else 1
            while stack and stack[-1][0] >= level:
                stack.pop()
            if str(node.id) not in body_less_headings:
                stack.append((level, node.text or ""))
                if include_previous_heading or tables_only:
                    continue  # 제목 글은 청크 앞 경로 머리말로 들어간다
                # 본문이 있는 제목도 그 구획 첫 청크의 글로 담는다. 구획 경로는 LLM 에 주는 발췌문에 들어가지 않아,
                # "제11조(요양보상) ① 임․직원이 …"처럼 제목으로 분류된 조문 첫 항이 답변 근거에서 빠졌다
                # (문서 104건 가운데 89건, 2026-11-27)
            # 아래에 본문이 없는 제목은 어느 청크의 구획 경로에도 들어가지 않으므로 문단처럼 담는다

        if node.span_start is None or node.span_end is None:
            continue  # 방어적 — TABLE을 포함한 모든 내용 노드 타입은 span을 가져야 함

        is_table = node.node_type == "TABLE"
        if tables_only and not is_table:
            continue

        node_len = node.span_end - node.span_start
        continues = not is_table and _continues_sentence(text, buf_end, node)
        if open_tail and not continues:
            flush()  # 이어지는 문장이 아니면 남겨 둔 조각은 예전처럼 따로 청크가 된다
        open_tail = False

        if is_table and preserve_table:
            # 표 바로 앞에 제목만 남아 있으면 그 표의 제목이므로 표 청크 앞에 붙인다(제목만 든 짧은 청크를 만들지 않는다)
            title_only = bool(buf_node_ids) and set(buf_node_ids) <= heading_node_ids
            if not (title_only and (buf_end - buf_start) + node_len <= max_chars):
                flush()
            if node_len > max_chars and split_long_paragraph:
                split_oversized(node)
            else:
                append_to_buffer(node)
                flush()
            continue

        would_overflow = bool(buf_node_ids) and (buf_end - buf_start) + node_len > max_chars
        if would_overflow and continues:
            open_tail = False
            carry_open_sentence()
            if (buf_end - buf_start) + node_len > max_chars:
                if split_long_paragraph:
                    spans = [*buf_spans, (str(node.id), node.span_start, node.span_end)]
                    set_buffer([])
                    split_range(spans)
                    continue
                flush()
            append_to_buffer(node)
            continue
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
    # "표는 항상 자기 혼자만의 청크" 보장이 꼬리 병합으로 깨지는 것을 방지한다.
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

    if merge_small_sections:
        return _merge_small_sections(chunks, text, min_chars, max_chars, table_node_ids, with_prefix)
    return chunks


def _merge_small_sections(chunks, text, min_chars, max_chars, table_node_ids, with_prefix) -> list[ChunkSpan]:
    """min_chars보다 짧은 청크를 이웃 청크와 합친다(구획이 달라도). 표 청크는 건드리지 않고, 합친 길이가
    max_chars를 넘으면 합치지 않는다. 구획 경로는 더 긴 쪽을 따른다.

    자동 구조 기준(컬렉션 기본값 size에서 전환)에서만 쓴다. 소제목이 촘촘한 슬라이드형 PDF에서 제목마다
    청크를 닫으면 6~50자짜리 조각이 쏟아져 품질 검사에 걸리고 검색 단서도 약해졌다(2026-11-13)."""
    def is_table(chunk: ChunkSpan) -> bool:
        # 칸 하나짜리 짧은 표("[표 1] 1. 사업개요 |")는 HWP 공고문이 제목 대신 쓰는 것이라 표로 지키지 않는다
        return bool(table_node_ids.intersection(chunk.source_node_ids)) and chunk.end - chunk.start >= min_chars

    merged: list[ChunkSpan] = []
    for chunk in chunks:
        prev = merged[-1] if merged else None
        can_merge = (
            prev is not None
            and not is_table(prev) and not is_table(chunk)
            and prev.end <= chunk.start
            and min(prev.end - prev.start, chunk.end - chunk.start) < min_chars
            and chunk.end - prev.start <= max_chars
        )
        # 표 바로 앞의 짧은 한 줄("※ ... 비교표")은 그 표의 제목이므로 표 앞에 붙인다(표 내용은 그대로 한 덩어리)
        is_caption_of_table = (
            prev is not None
            and not is_table(prev) and is_table(chunk)
            and prev.end <= chunk.start
            and prev.end - prev.start < min_chars
            and chunk.end - prev.start <= max_chars
        )
        if not (can_merge or is_caption_of_table):
            merged.append(chunk)
            continue
        longer = prev if prev.end - prev.start >= chunk.end - chunk.start else chunk
        merged[-1] = ChunkSpan(
            with_prefix(text[prev.start:chunk.end], longer.section_path),
            prev.start, chunk.end, longer.section_path,
            prev.source_node_ids + chunk.source_node_ids,
        )
    return merged
