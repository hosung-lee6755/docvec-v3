import { describe, expect, it } from 'vitest'

import { splitAutolink } from './autolink'

describe('splitAutolink', () => {
  it('stops the address before a Korean particle and an unbalanced closing paren', () => {
    expect(splitAutolink('www.ntis.go.kr)에')).toEqual({
      href: 'http://www.ntis.go.kr',
      label: 'www.ntis.go.kr',
      rest: ')에',
    })
  })

  it('keeps balanced parentheses and drops trailing sentence punctuation', () => {
    expect(splitAutolink('https://ko.wikipedia.org/wiki/A_(B).')).toEqual({
      href: 'https://ko.wikipedia.org/wiki/A_(B)',
      label: 'https://ko.wikipedia.org/wiki/A_(B)',
      rest: '.',
    })
  })

  it('leaves a plain address untouched', () => {
    expect(splitAutolink('https://example.com/a?b=1')).toEqual({
      href: 'https://example.com/a?b=1',
      label: 'https://example.com/a?b=1',
      rest: '',
    })
  })

  it('returns null for text that is not an address', () => {
    expect(splitAutolink('관련 자료')).toBeNull()
    expect(splitAutolink('www.')).toBeNull()
  })
})
