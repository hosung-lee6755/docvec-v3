import { describe, expect, it } from 'vitest'
import { QUALITY_CATEGORY_LABELS } from './documentDetailHelpers'
import { QUALITY_CRITERIA, QUALITY_OVERALL_RULES, sourceRecallSkipReason } from './qualityCriteria'

describe('qualityCriteria', () => {
  it('점수 탭에 나오는 모든 항목에 산정 기준 설명이 있다', () => {
    const described = QUALITY_CRITERIA.map((c) => c.key).sort()
    expect(described).toEqual(Object.keys(QUALITY_CATEGORY_LABELS).sort())
  })

  it('모든 항목이 계산 방식과 한계를 설명한다', () => {
    for (const c of QUALITY_CRITERIA) {
      expect(c.how.length).toBeGreaterThan(20)
      expect(c.limits.length).toBeGreaterThan(10)
    }
  })

  it('정규화는 측정하지 않는 고정값임을 밝힌다', () => {
    expect(QUALITY_CRITERIA.find((c) => c.key === 'normalization')?.basis).toBe('고정')
  })

  it('원문 재현율을 못 잰 사유를 알려 주고, 쟀거나 과거 리포트면 null 이다', () => {
    expect(sourceRecallSkipReason('no_text_layer')).toContain('스캔본')
    expect(sourceRecallSkipReason('unsupported_format')).toContain('PDF가 아닌')
    expect(sourceRecallSkipReason('error')).toContain('읽지 못해')
    expect(sourceRecallSkipReason('measured')).toBeNull()
    expect(sourceRecallSkipReason(undefined)).toBeNull()
  })

  it('종합점수 산식과 상태 판정 규칙을 설명한다', () => {
    expect(QUALITY_OVERALL_RULES.join(' ')).toContain('단순 평균')
    expect(QUALITY_OVERALL_RULES.join(' ')).toContain('상태 판정')
  })
})
