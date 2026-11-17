// 품질 경고가 가리키는 대상(청크, 쪽, 목차 항목)을 보고서에서 꺼낸다.
// 경고 문구만 보여 주면 상세 화면에서 어느 항목인지 찾을 수 없어서(2026-11-17), 탭들이 이 값을 써서 짚어 준다.
import type { QualityMetrics, QualityReport } from '../hooks/useDocumentRuns'

export type ChunkWarningKind = 'short' | 'long'

export const CHUNK_WARNING_LABELS: Record<ChunkWarningKind, string> = {
  short: '너무 짧음',
  long: '너무 김',
}

// 보고서에 대상 목록이 없을 때(오래된 보고서) 쓰는 기준. quality_check 블록의 기본값과 같다
const FALLBACK_SHORT_CHARS = 50
const FALLBACK_LONG_CHARS = 2000

/** 경고 종류별 대상 청크 id. 청크 경고가 아니면 undefined. */
export function warningChunkIds(
  category: string | null | undefined, metrics: QualityMetrics | null | undefined,
): string[] | undefined {
  if (category === 'chunking_short') return metrics?.short_chunk_ids
  if (category === 'chunking_long') return metrics?.long_chunk_ids
  return undefined
}

/** 청크 id → 경고 종류. 보고서가 없으면 null을 돌려주고, 그때는 chunkWarningKind가 글자 수로 판단한다. */
export function chunkWarningKinds(report: QualityReport | null | undefined): Map<string, ChunkWarningKind> | null {
  if (!report?.metrics) return null
  const { short_chunk_ids: shortIds, long_chunk_ids: longIds } = report.metrics
  if (!shortIds && !longIds) return null
  const kinds = new Map<string, ChunkWarningKind>()
  for (const id of shortIds ?? []) kinds.set(id, 'short')
  for (const id of longIds ?? []) kinds.set(id, 'long')
  return kinds
}

export function chunkWarningKind(
  chunk: { id: string; text: string }, kinds: Map<string, ChunkWarningKind> | null,
): ChunkWarningKind | null {
  if (kinds) return kinds.get(chunk.id) ?? null
  if (chunk.text.length < FALLBACK_SHORT_CHARS) return 'short'
  if (chunk.text.length > FALLBACK_LONG_CHARS) return 'long'
  return null
}

/** [3, 7, 8, 9, 12] → "3, 7~9, 12" */
export function formatPageRanges(pages: number[]): string {
  const sorted = [...new Set(pages)].sort((a, b) => a - b)
  const parts: string[] = []
  let start: number | null = null
  let previous: number | null = null
  for (const page of sorted) {
    if (start === null || previous === null) {
      start = page
    } else if (page !== previous + 1) {
      parts.push(start === previous ? `${start}` : `${start}~${previous}`)
      start = page
    }
    previous = page
  }
  if (start !== null && previous !== null) parts.push(start === previous ? `${start}` : `${start}~${previous}`)
  return parts.join(', ')
}

export function structureWarnings(report: QualityReport | null | undefined): string[] {
  if (!report?.warnings) return []
  return report.warnings.filter((_, index) => report.warning_categories?.[index] === 'structure')
}
