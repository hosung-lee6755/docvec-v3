"""표 행(rows) 데이터를 GFM markdown 표로 렌더링 — chunk_strategies.py의 표
오버사이즈 행 그룹 분할과 structure_blocks.py의 elements 표시 양쪽에서
공유해서 쓴다."""


def _escape_cell(cell: str) -> str:
    return (cell or "").replace("\n", " ").replace("|", "\\|").strip()


def rows_to_markdown(rows: list[list[str]]) -> str:
    """첫 행을 헤더로 사용해 `| a | b |\\n|---|---|\\n| c | d |` 형태로 렌더링한다.
    빈 rows는 빈 문자열을 반환하고, 1행(헤더만)짜리 표도 구분선까지 포함해
    유효한 markdown 표로 렌더링한다."""
    if not rows:
        return ""

    header = rows[0]
    col_count = len(header)
    lines = [
        "| " + " | ".join(_escape_cell(c) for c in header) + " |",
        "|" + "|".join(["---"] * col_count) + "|",
    ]
    for row in rows[1:]:
        padded = list(row) + [""] * (col_count - len(row))
        lines.append("| " + " | ".join(_escape_cell(c) for c in padded[:col_count]) + " |")
    return "\n".join(lines)
