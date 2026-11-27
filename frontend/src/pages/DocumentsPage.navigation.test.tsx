import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import DocumentsPage from './DocumentsPage'

const calls = vi.hoisted(() => ({ useDocuments: [] as Array<{ page: number; limit: number; sortBy: string }> }))

const DOCS = ['a', 'b', 'c'].map((id) => ({
  id, filename: `${id}.hwp`, original_filename: `${id}.hwp`, status: 'INDEXED', file_size: 1, collection_id: null,
  created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z', tags: [], suggested_tags: [],
  lifecycle_state: 'current', version_number: 1, lineage_id: id,
}))

vi.mock('../hooks/useDocuments', () => {
  const mutation = () => ({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false })
  return {
    useDocuments: (params: { page: number; limit: number; sortBy: string }) => {
      calls.useDocuments.push(params)
      return { data: { items: DOCS, total: 60 }, isLoading: false, isError: false, refetch: vi.fn() }
    },
    useDeleteDocument: mutation,
    useBatchDeleteDocuments: mutation,
    useBatchReprocessDocuments: mutation,
    useBatchMoveDocuments: mutation,
    summarizeMoveResults: () => ({ text: '', isError: false }),
  }
})
vi.mock('../hooks/useDocumentStats', () => ({ useDocumentStats: () => ({ data: { total_documents: 60 } }) }))
vi.mock('../hooks/useCollections', () => ({ useCollections: () => ({ data: { items: [] } }) }))

function Detail() {
  const navigate = useNavigate()
  return <button type="button" onClick={() => navigate(-1)}>뒤로</button>
}

function Where() {
  const location = useLocation()
  return <div data-testid="where">{`${location.pathname}${location.search}`}</div>
}

function renderAt(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/documents" element={<><DocumentsPage /><Where /></>} />
          <Route path="/documents/:id" element={<Detail />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('DocumentsPage navigation', () => {
  beforeEach(() => {
    calls.useDocuments.length = 0
    Element.prototype.scrollIntoView = vi.fn()
  })

  it('comes back from a document to the same page, size and sort, at the row that was opened', () => {
    // 2026-11-27: 상세에서 뒤로 오면 1쪽으로 돌아가 보던 문서 다음 문서를 다시 찾아야 했다
    renderAt('/documents?page=3&limit=10&sort=filename&order=asc')
    expect(calls.useDocuments[calls.useDocuments.length - 1]).toMatchObject({ page: 3, limit: 10, sortBy: 'filename' })

    fireEvent.click(screen.getByRole('button', { name: 'b.hwp' }))
    fireEvent.click(screen.getByRole('button', { name: '뒤로' }))

    expect(screen.getByTestId('where').textContent).toBe('/documents?page=3&limit=10&sort=filename&order=asc')
    expect(calls.useDocuments[calls.useDocuments.length - 1]).toMatchObject({ page: 3, limit: 10, sortBy: 'filename' })
    const row = document.querySelector('[data-document-id="b"]')
    expect(row?.classList.contains('is-recent')).toBe(true)
    expect(Element.prototype.scrollIntoView).toHaveBeenCalled()
  })

  it('moves to the first page when the page size changes', () => {
    renderAt('/documents?page=3')

    fireEvent.change(screen.getByRole('combobox', { name: '표시 건수' }), { target: { value: '50' } })

    expect(screen.getByTestId('where').textContent).toBe('/documents?limit=50')
  })

  it('keeps the page in the address when moving between pages', () => {
    renderAt('/documents')

    fireEvent.click(screen.getByRole('button', { name: '다음' }))

    expect(screen.getByTestId('where').textContent).toBe('/documents?page=2')
  })
})
