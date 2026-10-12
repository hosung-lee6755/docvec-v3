import { describe, it, expect } from 'vitest'
import { diffWords } from './diffWords'

describe('diffWords', () => {
  it('returns a single equal segment when texts are identical', () => {
    const ops = diffWords('hello world', 'hello world')
    expect(ops).toEqual([{ type: 'equal', text: 'hello world' }])
  })

  it('marks removed words when after text has fewer words', () => {
    const ops = diffWords('hello there world', 'hello world')
    const removed = ops.filter((op) => op.type === 'remove').map((op) => op.text).join('')
    expect(removed).toContain('there')
  })

  it('marks added words when after text has extra words', () => {
    const ops = diffWords('hello world', 'hello brave new world')
    const added = ops.filter((op) => op.type === 'add').map((op) => op.text).join('')
    expect(added).toContain('brave')
    expect(added).toContain('new')
  })

  it('handles fully replaced text without crashing', () => {
    const ops = diffWords('foo', 'bar')
    expect(ops.some((op) => op.type === 'remove' && op.text === 'foo')).toBe(true)
    expect(ops.some((op) => op.type === 'add' && op.text === 'bar')).toBe(true)
  })

  it('handles an empty before text (all additions)', () => {
    const ops = diffWords('', 'new text')
    expect(ops.every((op) => op.type === 'add')).toBe(true)
  })
})
