/**
 * 원문 대조 탭은 파싱 본문을 원본 쪽에 맞춰 잘라 쪽마다 따로 그린다. 표가 두 쪽에 걸치면 뒤 쪽 조각에는 머리 행과
 * 구분선(|---|)이 없어 마크다운이 표로 읽지 못하고 "| 부산 | 120 |" 같은 글줄로 그렸다(2026-11-26). 쪽보다 긴 표
 * 행(글상자)은 행 가운데에서 잘려 앞 쪽 끝에 닫는 "|"가, 뒤 쪽 처음에 여는 "|"가 없다.
 *
 * closeSplitTables 는 잘린 행을 닫고 열어 주고, 머리 행 없이 시작하는 표 조각에 빈 머리 행을 붙인다. 빈 머리 행은
 * isEmptyTableHead 로 알아보고 화면에서 그리지 않는다. 본문 글은 하나도 바꾸지 않는다.
 */

const DIVIDER_ROW = /^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?$/

function isTableLine(line: string): boolean {
  return line.trimStart().startsWith('|')
}

function isDivider(line: string): boolean {
  return DIVIDER_ROW.test(line.trim())
}

function cellCount(row: string): number {
  const inner = row.trim().replace(/^\|/, '').replace(/(?<!\\)\|$/, '')
  return inner.split(/(?<!\\)\|/).length
}

function emptyHead(columns: number): string[] {
  return [`|${'  |'.repeat(columns)}`, `|${' --- |'.repeat(columns)}`]
}

/**
 * 앞 쪽에서 잘려 넘어온 행("글 |")을 여는 "|"로 다시 연다. 다음 줄이 표 줄일 때만 그렇게 본다. 잘린 칸이 뒤쪽 열이면
 * 그 앞 열을 빈 칸으로 채워 글이 제 열에 놓이게 한다(다음 행의 칸 수가 표의 열 수다).
 */
function reopenLeadingRow(lines: string[]): string[] {
  const first = lines.findIndex((line) => line.trim() !== '')
  if (first < 0) return lines
  const line = lines[first]
  const next = lines[first + 1]
  if (isTableLine(line) || !line.trimEnd().endsWith('|') || next === undefined || !isTableLine(next)) return lines
  const reopened = `| ${line}`
  const missing = Math.max(cellCount(next) - cellCount(reopened), 0)
  return [...lines.slice(0, first), `|${'  |'.repeat(missing)} ${line}`, ...lines.slice(first + 1)]
}

/** 다음 쪽으로 이어지는 마지막 행("| 글")을 닫는 "|"로 닫는다. */
function closeTrailingRow(lines: string[]): string[] {
  let last = lines.length - 1
  while (last >= 0 && lines[last].trim() === '') last -= 1
  if (last < 0) return lines
  const line = lines[last]
  if (!isTableLine(line) || line.trimEnd().endsWith('|')) return lines
  return [...lines.slice(0, last), `${line.trimEnd()} |`, ...lines.slice(last + 1)]
}

/** 머리 행과 구분선 없이 시작하는 표 줄 묶음 앞에 빈 머리 행을 붙인다. */
function headOrphanBlocks(lines: string[]): string[] {
  const out: string[] = []
  let index = 0
  while (index < lines.length) {
    if (!isTableLine(lines[index])) {
      out.push(lines[index])
      index += 1
      continue
    }
    const block: string[] = []
    while (index < lines.length && isTableLine(lines[index])) {
      block.push(lines[index])
      index += 1
    }
    const startsAtDivider = isDivider(block[0])
    const hasHead = block.length > 1 && isDivider(block[1])
    if (startsAtDivider) out.push(emptyHead(cellCount(block[0]))[0])
    else if (!hasHead && !block.some(isDivider)) out.push(...emptyHead(cellCount(block[0])))
    out.push(...block)
  }
  return out
}

export function closeSplitTables(text: string): string {
  const lines = closeTrailingRow(reopenLeadingRow(text.split('\n')))
  return headOrphanBlocks(lines).join('\n')
}

interface HastLike {
  type?: string
  value?: string
  children?: HastLike[]
}

function textOf(node: HastLike): string {
  if (node.type === 'text') return node.value ?? ''
  return (node.children ?? []).map(textOf).join('')
}

/** closeSplitTables 가 붙인 빈 머리 행인지. 머리 칸이 모두 비었으면 그린다고 보이는 것이 없다. */
export function isEmptyTableHead(node: HastLike | undefined): boolean {
  if (!node) return false
  return textOf(node).trim() === ''
}
