import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import DocumentsPage from './DocumentsPage'

// 지금 받은 페이지에는 처리 중 문서가 없지만, 보이는 문서 전체에는 처리 중 1건·검토 대기 2건·실패 3건이 있다
vi.mock('../hooks/useDocuments', () => {
  const mutation = () => ({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false })
  return {
    useDocuments: () => ({ data: { items: [], total: 20 }, isLoading: false, isError: false, refetch: vi.fn() }),
    useDeleteDocument: mutation,
    useBatchDeleteDocuments: mutation,
    useBatchReprocessDocuments: mutation,
    useBatchMoveDocuments: mutation,
    summarizeMoveResults: () => ({ text: '', isError: false }),
  }
})
vi.mock('../hooks/useDocumentStats', () => ({
  useDocumentStats: () => ({
    data: { total_documents: 70, processing: 1, indexed: 64, waiting_review: 2, failed: 3, collections: 4 },
  }),
}))
vi.mock('../hooks/useCollections', () => ({ useCollections: () => ({ data: { items: [] } }) }))

function statValue(label: string): string | undefined {
  const labelEl = screen.getAllByText(label).find((el) => el.classList.contains('ds-stat__label'))
  return labelEl?.closest('.ds-stat')?.querySelector('.ds-stat__value')?.textContent ?? undefined
}

describe('DocumentsPage summary strip', () => {
  it('shows the same document-wide counts as the dashboard, not the current page', () => {
    // 2026-11-26: 20건씩 보면 "처리 중 0", 100건씩 보면 "처리 중 1"로 표시 건수에 따라 값이 달랐다
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={['/documents']}>
          <DocumentsPage />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    expect(statValue('전체')).toBe('70')
    expect(statValue('처리 중')).toBe('1')
    expect(statValue('검토 대기')).toBe('2')
    expect(statValue('실패')).toBe('3')
    expect(screen.queryByText('이 페이지')).toBeNull()
  })
})
