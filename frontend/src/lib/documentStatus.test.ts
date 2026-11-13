import { describe, expect, it } from 'vitest'
import { STATUS_FILTER_OPTIONS, STATUS_LABELS, statusFilterValue } from './documentStatus'

describe('STATUS_FILTER_OPTIONS', () => {
  it('같은 이름의 상태는 상태 거르기 목록에 한 번만 나온다', () => {
    const labels = STATUS_FILTER_OPTIONS.map((o) => o.label)
    expect(new Set(labels).size).toBe(labels.length)
  })

  it('검토대기 하나로 옛 파이프라인과 워크플로우의 검토 대기 문서를 함께 거른다', () => {
    const review = STATUS_FILTER_OPTIONS.filter((o) => o.label === '검토대기')
    expect(review).toHaveLength(1)
    expect(review[0].value.split(',').sort()).toEqual(['REVIEW_PENDING', 'WAITING_REVIEW'])
  })

  it('모든 상태가 어느 한 선택지에 들어 있다', () => {
    const covered = STATUS_FILTER_OPTIONS.flatMap((o) => o.value.split(','))
    expect(covered.sort()).toEqual(Object.keys(STATUS_LABELS).sort())
  })
})

describe('statusFilterValue', () => {
  it('주소에 상태 하나만 있어도 그 상태가 든 선택지 값으로 맞춘다', () => {
    const review = STATUS_FILTER_OPTIONS.find((o) => o.label === '검토대기')?.value
    expect(review).toBeDefined()
    expect(statusFilterValue('WAITING_REVIEW')).toBe(review)
    expect(statusFilterValue('REVIEW_PENDING')).toBe(review)
  })

  it('이름이 겹치지 않는 상태와 빈 값은 그대로 둔다', () => {
    expect(statusFilterValue('FAILED')).toBe('FAILED')
    expect(statusFilterValue('')).toBe('')
    expect(statusFilterValue('UNKNOWN')).toBe('UNKNOWN')
  })
})
