import { describe, expect, it } from 'vitest'
import { failureCauseHeadline, formatElapsed, groupFailureCauses, isStale } from './documentQueues'
import type { FailureQueueItem } from '../hooks/useDocumentQueues'

const NOW = Date.parse('2026-11-12T12:00:00Z')

function failure(error_message: string | null): FailureQueueItem {
  return {
    document_id: Math.random().toString(36), filename: 'a.pdf', collection_id: null, collection_name: null,
    run_id: null, failed_block_type: null, error_code: null, error_message, failed_at: null,
    failure_count: 1, can_retry: false,
  }
}

describe('formatElapsed', () => {
  it('지난 시간을 분, 시간, 일 단위로 말한다', () => {
    expect(formatElapsed('2026-11-12T11:59:30Z', NOW)).toBe('방금')
    expect(formatElapsed('2026-11-12T11:45:00Z', NOW)).toBe('15분 전')
    expect(formatElapsed('2026-11-12T09:00:00Z', NOW)).toBe('3시간 전')
    expect(formatElapsed('2026-11-10T12:00:00Z', NOW)).toBe('2일 전')
  })

  it('값이 없으면 줄표를 보인다', () => {
    expect(formatElapsed(null, NOW)).toBe('-')
  })
})

describe('isStale', () => {
  it('하루 넘게 기다린 것만 오래됐다고 본다', () => {
    expect(isStale('2026-11-11T11:00:00Z', NOW)).toBe(true)
    expect(isStale('2026-11-12T01:00:00Z', NOW)).toBe(false)
    expect(isStale(null, NOW)).toBe(false)
  })
})

describe('groupFailureCauses', () => {
  it('같은 원인끼리 묶고 많은 원인부터 돌려준다', () => {
    const groups = groupFailureCauses([
      failure('ReadTimeout: timed out'),
      failure('httpx.ReadTimeout'),
      failure('ConnectError: Connection refused'),
    ])
    expect(groups[0]).toEqual({ cause: '처리 시간이 초과되었습니다.', count: 2 })
    expect(groups[1].count).toBe(1)
  })

  it('원문이 다른 모르는 오류는 첫 문장이 같으면 한 묶음이 된다', () => {
    const groups = groupFailureCauses([failure('KeyError: a'), failure('ValueError: b')])
    expect(groups).toHaveLength(1)
    expect(groups[0].count).toBe(2)
  })
})

describe('failureCauseHeadline', () => {
  it('한국어 메시지는 그대로 쓴다', () => {
    expect(failureCauseHeadline('사용자가 검토를 반려하여 처리가 취소되었습니다')).toBe('사용자가 검토를 반려하여 처리가 취소되었습니다')
  })
})
