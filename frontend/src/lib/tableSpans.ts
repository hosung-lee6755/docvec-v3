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

// 원문 대조 화면에서 본문의 마크다운 표를 저장된 표(rows, spans)로 바꿔 그리기 위한 계산(2026-11-25).
// 마크다운 표는 칸을 합칠 수 없어, 표 탭에서는 합쳐 보이던 칸이 원문 대조에서는 겹치거나 비어 보였다.
// 서버는 본문의 표를 저장된 rows 로 만든 마크다운(table_markdown.rows_to_markdown)으로 적으므로, 같은 규칙으로
// 마크다운을 만들어 본문에서 찾으면 그 자리가 어느 표인지 알 수 있다. 정제 단계에서 글이 바뀌어 찾지 못한 표는
// 마크다운 그대로 둔다.

export interface SpannedTable {
  rows: string[][]
  spans?: TableSpan[] | null
}

export type TextPart<T extends SpannedTable> = { kind: 'text'; text: string } | { kind: 'table'; table: T }

const escapeCell = (cell: string) => (cell ?? '').replace(/\n/g, ' ').replace(/\|/g, '\|').trim()

export function tableMarkdown(rows: string[][]): string {
  if (!rows.length) return ''
  const width = rows[0].length
  const line = (row: string[]) => {
    const padded = [...row, ...Array(Math.max(width - row.length, 0)).fill('')].slice(0, width)
    return `| ${padded.map(escapeCell).join(' | ')} |`
  }
  return [line(rows[0]), `|${Array(width).fill('---').join('|')}|`, ...rows.slice(1).map(line)].join('\n')
}

export function splitByTables<T extends SpannedTable>(text: string, tables: T[] | null | undefined): TextPart<T>[] {
  const found: { start: number; end: number; table: T }[] = []
  for (const table of tables ?? []) {
    const markdown = tableMarkdown(table.rows)
    if (!markdown) continue
    // 같은 표가 두 번 저장된 경우를 위해 이미 쓴 자리 뒤부터 찾는다
    let from = 0
    while (from <= text.length) {
      const start = text.indexOf(markdown, from)
      if (start < 0) break
      const end = start + markdown.length
      if (!found.some((f) => start < f.end && end > f.start)) {
        found.push({ start, end, table })
        break
      }
      from = start + 1
    }
  }
  found.sort((a, b) => a.start - b.start)
  const parts: TextPart<T>[] = []
  let cursor = 0
  for (const { start, end, table } of found) {
    if (start > cursor) parts.push({ kind: 'text', text: text.slice(cursor, start) })
    parts.push({ kind: 'table', table })
    cursor = end
  }
  if (cursor < text.length || !parts.length) parts.push({ kind: 'text', text: text.slice(cursor) })
  return parts
}
