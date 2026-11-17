// 전체 점검 2-2 — 합친 칸이 있는 표를 원래 모양으로 그리기 위한 계산.
// 서버가 주는 rows는 열이 맞는 격자이고(세로로 합친 칸의 글은 아래 줄에도 되풀이돼 있다),
// spans는 합친 칸의 위치와 크기다. 여기서 가려지는 칸을 빼고 rowSpan, colSpan을 붙인다.

export interface TableSpan {
  row: number
  col: number
  row_span: number
  col_span: number
}

export interface RenderCell {
  text: string
  column: number
  rowSpan: number
  colSpan: number
}

const key = (row: number, col: number) => `${row}:${col}`

export function layoutCells(rows: string[][], spans: TableSpan[] | null | undefined): RenderCell[][] {
  const anchors = new Map<string, TableSpan>()
  const covered = new Set<string>()
  for (const span of spans ?? []) {
    // 격자 밖을 가리키는 값은 버린다. 그대로 쓰면 칸이 사라진다
    if (span.row < 0 || span.col < 0 || span.row >= rows.length || span.row_span < 1 || span.col_span < 1) continue
    anchors.set(key(span.row, span.col), span)
    for (let r = span.row; r < span.row + span.row_span; r += 1) {
      for (let c = span.col; c < span.col + span.col_span; c += 1) {
        if (r !== span.row || c !== span.col) covered.add(key(r, c))
      }
    }
  }
  return rows.map((row, r) =>
    row.flatMap((text, c) => {
      if (covered.has(key(r, c))) return []
      const span = anchors.get(key(r, c))
      return [{
        text,
        column: c,
        rowSpan: span ? Math.min(span.row_span, rows.length - r) : 1,
        colSpan: span ? Math.min(span.col_span, row.length - c) : 1,
      }]
    }),
  )
}
