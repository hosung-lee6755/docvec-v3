import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import DictionaryApplicationsTab from './DictionaryApplicationsTab'
import type { DictionaryApplicationItem } from '../../hooks/useDocumentStructure'

const toggle = vi.fn()
let applications: DictionaryApplicationItem[]
let excludedIds: string[]
let exclusionEntries: { entry_id: string; term: string | null; entry_type: string | null; created_at: string }[]

vi.mock('../../hooks/useDocumentStructure', () => ({
  useDictionaryApplications: () => ({
    isLoading: false,
    data: { document_id: 'doc-1', run_id: 'r-1', pending_revert_count: 0, applications, excluded_entry_ids: excludedIds },
  }),
  useDictionaryExclusions: () => ({ data: { document_id: 'doc-1', entries: exclusionEntries } }),
  useRevertDictionaryApplication: () => ({ mutate: vi.fn(), isPending: false }),
  useToggleDictionaryExclusion: () => ({ mutate: toggle, isPending: false, isError: false }),
}))

const app = (overrides: Partial<DictionaryApplicationItem> = {}): DictionaryApplicationItem => ({
  id: 'a-1', dictionary_type: 'SYNONYM', entry_id: 'e-1', dictionary_version: 3,
  original_text: '매상', normalized_text: '매출', node_id: null, chunk_id: null,
  start_offset: 10, end_offset: 12, reverted: false, created_at: '',
  context_before: '올해 1분기 ', context_after: ' 실적은', entry_term: '매출', ...overrides,
})

const renderTab = () => render(<DictionaryApplicationsTab documentId="doc-1" onReprocessFromDictionary={vi.fn()} />)

describe('DictionaryApplicationsTab', () => {
  beforeEach(() => {
    toggle.mockReset()
    applications = [app(), app({ id: 'a-2' })]
    excludedIds = []
    exclusionEntries = []
  })

  it('shows where the dictionary changed the text, with surrounding context', () => {
    renderTab()
    expect(screen.getAllByText(/올해 1분기/)).toHaveLength(2)
    expect(screen.getAllByText('매상')[0].tagName).toBe('S')
  })

  it('groups applications by entry and turns an entry off for this document only', () => {
    renderTab()
    expect(screen.getByText('2건')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '이 문서에서 끄기' }))
    expect(toggle).toHaveBeenCalledWith({ documentId: 'doc-1', entryId: 'e-1', exclude: true })
  })

  it('asks for reprocessing while a turned-off entry is still applied', () => {
    excludedIds = ['e-1']
    renderTab()
    expect(screen.getByText(/이 문서에서 끈 항목 1개/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '다시 적용' }))
    expect(toggle).toHaveBeenCalledWith({ documentId: 'doc-1', entryId: 'e-1', exclude: false })
  })

  it('keeps an already-reprocessed exclusion visible so it can be turned back on', () => {
    applications = []
    excludedIds = ['e-9']
    exclusionEntries = [{ entry_id: 'e-9', term: '불용어예시', entry_type: 'stopword', created_at: '' }]
    renderTab()
    expect(screen.getByText('불용어예시')).toBeInTheDocument()
    expect(screen.getByText('적용 안 됨')).toBeInTheDocument()
    expect(screen.queryByText(/재처리해야/)).not.toBeInTheDocument()
  })
})
