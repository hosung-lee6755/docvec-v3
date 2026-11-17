import { describe, expect, it } from 'vitest'
import type { QualityReport } from '../hooks/useDocumentRuns'
import {
  chunkWarningKind, chunkWarningKinds, formatPageRanges, structureWarnings, warningChunkIds,
} from './qualityTargets'

function report(overrides: Partial<QualityReport>): QualityReport {
  return {
    id: 'q1', run_id: 'r1', overall_score: 80, scores: null, metrics: null, warnings: null,
    warning_categories: null, status: 'REVIEW_REQUIRED', reviewed_by: null, reviewed_at: null,
    ...overrides,
  } as QualityReport
}

describe('formatPageRanges', () => {
  it('joins consecutive pages into ranges', () => {
    expect(formatPageRanges([3, 7, 8, 9, 12])).toBe('3, 7~9, 12')
  })

  it('sorts and removes duplicates', () => {
    expect(formatPageRanges([5, 2, 2, 1])).toBe('1~2, 5')
  })

  it('returns an empty string for no pages', () => {
    expect(formatPageRanges([])).toBe('')
  })
})

describe('chunk warning targets', () => {
  it('maps flagged chunk ids to their kind', () => {
    const kinds = chunkWarningKinds(report({ metrics: { short_chunk_ids: ['a'], long_chunk_ids: ['b'] } }))

    expect(kinds?.get('a')).toBe('short')
    expect(kinds?.get('b')).toBe('long')
    expect(chunkWarningKind({ id: 'c', text: '짧다' }, kinds)).toBeNull()
  })

  it('falls back to text length when the report has no id lists', () => {
    expect(chunkWarningKinds(report({ metrics: {} }))).toBeNull()
    expect(chunkWarningKind({ id: 'c', text: '짧다' }, null)).toBe('short')
    expect(chunkWarningKind({ id: 'c', text: '가'.repeat(2001) }, null)).toBe('long')
    expect(chunkWarningKind({ id: 'c', text: '가'.repeat(100) }, null)).toBeNull()
  })

  it('picks the id list that matches the warning category', () => {
    const metrics = { short_chunk_ids: ['a'], long_chunk_ids: ['b'] }

    expect(warningChunkIds('chunking_short', metrics)).toEqual(['a'])
    expect(warningChunkIds('chunking_long', metrics)).toEqual(['b'])
    expect(warningChunkIds('structure', metrics)).toBeUndefined()
  })
})

describe('structureWarnings', () => {
  it('keeps only the warnings in the structure category', () => {
    const value = report({
      warnings: ['빈 페이지 비율이 기준을 초과했습니다', '너무 짧은 청크가 3개 있습니다'],
      warning_categories: ['structure', 'chunking_short'],
    })

    expect(structureWarnings(value)).toEqual(['빈 페이지 비율이 기준을 초과했습니다'])
    expect(structureWarnings(null)).toEqual([])
  })
})
