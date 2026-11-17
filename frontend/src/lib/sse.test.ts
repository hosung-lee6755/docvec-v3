import { describe, expect, it } from 'vitest'
import { parseSse } from './sse'

describe('parseSse', () => {
  it('splits complete events and keeps the unfinished tail', () => {
    const result = parseSse('event: partial\ndata: {"text":"안녕"}\n\nevent: done\ndata: {"sta')

    expect(result.events).toEqual([{ event: 'partial', data: '{"text":"안녕"}' }])
    expect(result.rest).toBe('event: done\ndata: {"sta')
  })

  it('finishes the tail once the rest of the event arrives', () => {
    const first = parseSse('event: done\ndata: {"sta')
    const second = parseSse(`${first.rest}tus":"DONE"}\n\n`)

    expect(first.events).toEqual([])
    expect(second.events).toEqual([{ event: 'done', data: '{"status":"DONE"}' }])
    expect(second.rest).toBe('')
  })

  it('ignores keep-alive comments', () => {
    expect(parseSse(': keep-alive\n\nevent: timeout\ndata: {}\n\n').events).toEqual([
      { event: 'timeout', data: '{}' },
    ])
  })

  it('accepts CRLF line endings and a missing event name', () => {
    expect(parseSse('data: a\r\ndata: b\r\n\r\n').events).toEqual([{ event: 'message', data: 'a\nb' }])
  })
})
