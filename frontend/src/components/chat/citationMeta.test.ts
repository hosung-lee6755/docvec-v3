import { describe, it, expect } from 'vitest'
import { formatCitationPlace, formatPageRange, formatSectionPath } from './citationMeta'

describe('citationMeta', () => {
  it('joins the page and the section path', () => {
    expect(formatCitationPlace({ page_number: 3, section_path: ['2장 운영', '2.1 백업'] })).toBe('3쪽 · 2장 운영 > 2.1 백업')
  })

  it('shows a page range only when the chunk spans pages', () => {
    expect(formatPageRange(3, 4)).toBe('3–4쪽')
    expect(formatPageRange(3, 3)).toBe('3쪽')
    expect(formatPageRange(3, null)).toBe('3쪽')
    expect(formatPageRange(3, 2)).toBe('3쪽')
  })

  it('works for old answers that carry neither the range nor the path', () => {
    expect(formatCitationPlace({ page_number: 5 })).toBe('5쪽')
    expect(formatCitationPlace({ page_number: null, section_path: null })).toBe('')
    expect(formatCitationPlace({})).toBe('')
  })

  it('shows the section path alone for formats without pages', () => {
    expect(formatCitationPlace({ page_number: null, section_path: ['개요'] })).toBe('개요')
  })

  it('drops blank headings', () => {
    expect(formatSectionPath(['  ', '1장', ''])).toBe('1장')
    expect(formatSectionPath([])).toBe('')
    expect(formatSectionPath(undefined)).toBe('')
  })
})
