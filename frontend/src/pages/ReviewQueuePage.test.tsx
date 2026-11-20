import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import ReviewQueuePage from './ReviewQueuePage'

const bulkApproveMutate = vi.fn()
const bulkRejectMutate = vi.fn()

const item = (id: string, extra: Record<string, unknown> = {}) => ({
  document_id: id, filename: `${id}.pdf`, collection_name: null, run_id: `run-${id}`,
  reasons: ['quality'], quality_status: null, overall_score: null, warnings: [], warning_categories: [],
  pii_pending_count: 0, pii_entity_types: [], waiting_since: new Date().toISOString(),
  ...extra,
})

const items = [item('a'), item('b', { reasons: ['pii'], pii_pending_count: 2 }), item('c', { run_id: null })]

vi.mock('../hooks/useDocumentQueues', () => {
  const idle = { mutate: vi.fn(), isPending: false, isError: false }
  return {
    useReviewQueue: () => ({
      data: { total: items.length, counts: { quality: 2, pii: 1 }, items },
      isLoading: false, isError: false, refetch: vi.fn(),
    }),
    useApproveReview: () => idle,
    useRejectReview: () => idle,
    useBulkApproveReview: () => ({ mutate: bulkApproveMutate, isPending: false, isError: false }),
    useBulkRejectReview: () => ({ mutate: bulkRejectMutate, isPending: false, isError: false }),
  }
})

vi.mock('../components/document-detail/PiiDetectionsTab', () => ({
  default: ({ documentId }: { documentId: string }) => <div>민감정보 패널 {documentId}</div>,
}))

const renderPage = () => render(<MemoryRouter><ReviewQueuePage /></MemoryRouter>)

describe('ReviewQueuePage bulk review', () => {
  beforeEach(() => {
    bulkApproveMutate.mockReset()
    bulkRejectMutate.mockReset()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
  })

  it('approves only the checked documents', () => {
    renderPage()
    expect(screen.getByRole('button', { name: '선택 승인하고 계속' })).toBeDisabled()

    fireEvent.click(screen.getByRole('checkbox', { name: 'b.pdf 선택' }))
    fireEvent.click(screen.getByRole('button', { name: '선택 승인하고 계속' }))

    expect(bulkApproveMutate).toHaveBeenCalledWith(['run-b'], expect.anything())
  })

  it('rejects the checked documents', () => {
    renderPage()

    fireEvent.click(screen.getByRole('checkbox', { name: 'a.pdf 선택' }))
    fireEvent.click(screen.getByRole('button', { name: '선택 반려' }))

    expect(bulkRejectMutate).toHaveBeenCalledWith(['run-a'], expect.anything())
  })

  it('approves every document that has a run with one click', () => {
    renderPage()

    fireEvent.click(screen.getByRole('button', { name: '전체 승인하고 계속' }))

    expect(bulkApproveMutate).toHaveBeenCalledWith(['run-a', 'run-b'], expect.anything())
  })

  it('selects all actionable documents with the header checkbox and skips ones without a run', () => {
    renderPage()

    fireEvent.click(screen.getByRole('checkbox', { name: '검토 대기 문서 전체 선택' }))

    expect(screen.getByText('2건 선택')).toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: 'c.pdf 선택' })).toBeDisabled()
  })

  it('does nothing when the confirmation is cancelled', () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    renderPage()

    fireEvent.click(screen.getByRole('button', { name: '전체 승인하고 계속' }))

    expect(bulkApproveMutate).not.toHaveBeenCalled()
  })

  it('opens the PII panel inline for documents waiting on PII approval', () => {
    renderPage()

    fireEvent.click(screen.getByRole('button', { name: '민감정보 보기' }))

    expect(screen.getByText('민감정보 패널 b')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '민감정보 접기' }))
    expect(screen.queryByText('민감정보 패널 b')).not.toBeInTheDocument()
  })
})
