import { describe, expect, it } from 'vitest'
import { formatElapsed } from './elapsedTime'

const NOW = Date.UTC(2026, 10, 16, 12, 0, 0)

describe('formatElapsed', () => {
  it('treats a timestamp without a timezone as UTC', () => {
    expect(formatElapsed('2026-11-16T11:30:00', NOW)).toBe('30분 전')
  })

  it('keeps an explicit timezone', () => {
    expect(formatElapsed('2026-11-16T20:00:00+09:00', NOW)).toBe('1시간 전')
  })

  it('moves from minutes to hours to days', () => {
    expect(formatElapsed('2026-11-16T11:59:40Z', NOW)).toBe('방금')
    expect(formatElapsed('2026-11-16T09:00:00Z', NOW)).toBe('3시간 전')
    expect(formatElapsed('2026-11-13T12:00:00Z', NOW)).toBe('3일 전')
  })

  it('never shows a negative time when clocks disagree', () => {
    expect(formatElapsed('2026-11-16T12:05:00Z', NOW)).toBe('방금')
  })
})
