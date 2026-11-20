import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import PiiDetectionsTab from './PiiDetectionsTab'

let role = 'admin'
const bulkMutate = vi.fn()
const revealAllMutate = vi.fn()

const detection = (id: string, extra: Record<string, unknown> = {}) => ({
  id, entity_type: 'PHONE', action: 'MASK', masked_value: '010-****-****', page_number: 1, node_id: null,
  start_offset: null, end_offset: null, confidence: 0.9, approved_by: null, approved_at: null, rejected: false,
  ...extra,
})

let detections = [detection('d-1'), detection('d-2', { approved_by: 'u-1' })]

vi.mock('../../store/authStore', () => ({
  useAuthStore: (select: (s: { user: { role: string } }) => unknown) => select({ user: { role } }),
}))

vi.mock('../../hooks/useDocumentStructure', () => {
  const idle = { mutate: vi.fn(), isPending: false, isError: false }
  return {
    usePiiDetections: () => ({ data: { document_id: 'doc-1', run_id: 'r-1', detections }, isLoading: false, isError: false }),
    useApprovePii: () => idle,
    useRejectPii: () => idle,
    useRevealPii: () => idle,
    useBulkReviewPii: () => ({ mutate: bulkMutate, isPending: false, isError: false }),
    useRevealAllPii: () => ({ mutate: revealAllMutate, isPending: false, isError: false }),
  }
})

describe('PiiDetectionsTab bulk actions', () => {
  beforeEach(() => {
    role = 'admin'
    detections = [detection('d-1'), detection('d-2', { approved_by: 'u-1' })]
    bulkMutate.mockReset()
    revealAllMutate.mockReset()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
  })

  it('approves and releases every detection after confirmation', () => {
    render(<PiiDetectionsTab documentId="doc-1" />)

    fireEvent.click(screen.getByRole('button', { name: '전체 승인' }))
    fireEvent.click(screen.getByRole('button', { name: '전체 해제' }))

    expect(bulkMutate).toHaveBeenNthCalledWith(1, { documentId: 'doc-1', approve: true }, expect.anything())
    expect(bulkMutate).toHaveBeenNthCalledWith(2, { documentId: 'doc-1', approve: false }, expect.anything())
  })

  it('does nothing when the confirmation is cancelled', () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    render(<PiiDetectionsTab documentId="doc-1" />)

    fireEvent.click(screen.getByRole('button', { name: '전체 승인' }))

    expect(bulkMutate).not.toHaveBeenCalled()
  })

  it('disables approve-all when everything is already approved', () => {
    detections = [detection('d-1', { approved_by: 'u-1' })]
    render(<PiiDetectionsTab documentId="doc-1" />)

    expect(screen.getByRole('button', { name: '전체 승인' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '전체 해제' })).toBeEnabled()
  })

  it('reveals every original at once and hides them all again', () => {
    revealAllMutate.mockImplementation((_vars, opts) => opts.onSuccess({ values: { 'd-1': '010-1234-5678' } }))
    render(<PiiDetectionsTab documentId="doc-1" />)
    expect(screen.getByRole('button', { name: '전체 숨기기' })).toBeDisabled()

    fireEvent.click(screen.getByRole('button', { name: '전체 원문 보기' }))

    expect(screen.getByText('010-1234-5678')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '전체 숨기기' }))
    expect(screen.queryByText('010-1234-5678')).not.toBeInTheDocument()
  })

  it('approves or releases only the checked detections', () => {
    render(<PiiDetectionsTab documentId="doc-1" />)
    expect(screen.getByRole('button', { name: '선택 승인' })).toBeDisabled()

    fireEvent.click(screen.getAllByRole('checkbox')[1])
    fireEvent.click(screen.getByRole('button', { name: '선택 승인' }))

    expect(bulkMutate).toHaveBeenCalledWith(
      { documentId: 'doc-1', approve: true, detectionIds: ['d-1'] }, expect.anything(),
    )
  })

  it('selects every detection with the header checkbox', () => {
    render(<PiiDetectionsTab documentId="doc-1" />)

    fireEvent.click(screen.getByRole('checkbox', { name: '민감정보 전체 선택' }))
    fireEvent.click(screen.getByRole('button', { name: '선택 해제' }))

    expect(bulkMutate).toHaveBeenCalledWith(
      { documentId: 'doc-1', approve: false, detectionIds: ['d-1', 'd-2'] }, expect.anything(),
    )
  })

  it('shows the original-text buttons only to administrators', () => {
    role = 'user'
    render(<PiiDetectionsTab documentId="doc-1" />)

    expect(screen.queryByRole('button', { name: '전체 원문 보기' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '전체 숨기기' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '전체 승인' })).toBeInTheDocument()
  })
})
