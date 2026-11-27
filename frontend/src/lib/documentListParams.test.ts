import { describe, it, expect } from 'vitest'
import { readDocumentListView, withDocumentListChange, withDocumentListPage } from './documentListParams'

describe('documentListParams', () => {
  it('reads the page, size, sort and filters from the address and falls back to defaults for bad values', () => {
    const view = readDocumentListView(new URLSearchParams('page=3&limit=50&sort=filename&order=asc&q=규정&quality=warning&lifecycle=all'))
    expect(view).toEqual({ page: 3, limit: 50, sortBy: 'filename', order: 'asc', filename: '규정', quality: 'warning', lifecycle: 'all' })

    const bad = readDocumentListView(new URLSearchParams('page=-2&limit=7&sort=evil&order=up&quality=x&lifecycle=y'))
    expect(bad).toEqual({ page: 1, limit: 20, sortBy: 'created_at', order: 'desc', filename: '', quality: '', lifecycle: '' })
  })

  it('goes back to the first page when the filter or sort changes and keeps other params', () => {
    const next = withDocumentListChange(new URLSearchParams('collection=c1&page=4'), { sortBy: 'status', order: 'asc' })
    expect(next.toString()).toBe('collection=c1&sort=status&order=asc')
  })

  it('leaves defaults out of the address', () => {
    const next = withDocumentListChange(new URLSearchParams('sort=filename&order=asc&limit=50&q=a'), {
      sortBy: 'created_at', order: 'desc', limit: 20, filename: '',
    })
    expect(next.toString()).toBe('')
    expect(withDocumentListPage(new URLSearchParams('page=3'), 1).toString()).toBe('')
    expect(withDocumentListPage(new URLSearchParams(''), 2).toString()).toBe('page=2')
  })
})
