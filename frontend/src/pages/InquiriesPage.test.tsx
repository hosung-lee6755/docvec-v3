import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import InquiriesPage from './InquiriesPage'

const h = vi.hoisted(() => ({
  role: 'viewer' as 'admin' | 'viewer',
  listData: undefined as unknown,
  detail: undefined as unknown,
  listParams: [] as Array<Record<string, unknown> | undefined>,
  createMutate: vi.fn(),
  replyMutate: vi.fn(),
  updateMutate: vi.fn(),
  deleteMutate: vi.fn(),
}))

vi.mock('../store/authStore', () => ({
  useAuthStore: (select: (s: { user: { id: string; role: string; email: string } }) => unknown) =>
    select({ user: { id: 'me', role: h.role, email: 'me@corp.local' } }),
}))

vi.mock('../hooks/useInquiries', () => ({
  useInquiries: (params?: Record<string, unknown>) => {
    h.listParams.push(params)
    return { data: h.listData, isLoading: false, isError: false, error: null, refetch: vi.fn() }
  },
  useInquiry: () => ({ data: h.detail, isLoading: false, isError: false, error: null, refetch: vi.fn() }),
  useOpenInquiryCount: () => ({ data: { total: 3 } }),
  useCreateInquiry: () => ({ mutate: h.createMutate, isPending: false, isError: false, error: null }),
  useAddInquiryMessage: () => ({ mutate: h.replyMutate, isPending: false, isError: false, error: null }),
  useUpdateInquiry: () => ({ mutate: h.updateMutate, isPending: false, isError: false, error: null }),
  useDeleteInquiry: () => ({ mutate: h.deleteMutate, isPending: false, isError: false, error: null }),
}))

const CREATED_AT = '2026-11-17T01:00:00Z'

function itemOf(overrides: Record<string, unknown> = {}) {
  return {
    id: 'i-1', title: 'PDF가 계속 실패합니다', category: 'error', status: 'open',
    author_id: 'me', author_name: '김직원', document_id: null,
    created_at: CREATED_AT, updated_at: CREATED_AT, ...overrides,
  }
}

function detailOf(overrides: Record<string, unknown> = {}) {
  return {
    ...itemOf(), error_snapshot: null, document: null,
    messages: [{ id: 'm-1', author_id: 'me', author_name: '김직원', is_admin: false, body: '세 번 실패합니다', created_at: CREATED_AT }],
    is_author: true, has_admin_reply: false, can_edit: true, can_reply: true, can_delete: true,
    ...overrides,
  }
}

function renderAt(path: string, state?: unknown) {
  return render(
    <MemoryRouter initialEntries={[{ pathname: path, state }]}>
      <Routes>
        <Route path="/inquiries" element={<InquiriesPage />} />
        <Route path="/inquiries/new" element={<InquiriesPage />} />
        <Route path="/inquiries/:inquiryId" element={<InquiriesPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('InquiriesPage', () => {
  beforeEach(() => {
    h.role = 'viewer'
    h.listData = { total: 1, items: [itemOf()] }
    h.detail = undefined
    h.listParams.length = 0
    h.createMutate.mockReset()
    h.replyMutate.mockReset()
    h.updateMutate.mockReset()
    h.deleteMutate.mockReset()
  })

  it('shows admins the open inquiries first and lets users see all of their own', () => {
    h.role = 'admin'
    const { unmount } = renderAt('/inquiries')
    expect(h.listParams[h.listParams.length - 1]).toMatchObject({ status: 'open' })
    unmount()

    h.role = 'viewer'
    renderAt('/inquiries')
    expect(h.listParams[h.listParams.length - 1]).toMatchObject({ status: 'all' })
  })

  it('prefills the compose form from a failed document and sends it as an error inquiry', () => {
    renderAt('/inquiries/new', { documentId: 'd-1', documentName: '계약서.pdf', category: 'error' })

    expect(screen.getByText('계약서.pdf')).toBeInTheDocument()
    expect(screen.getByLabelText('분류')).toHaveValue('error')
    fireEvent.change(screen.getByLabelText('제목'), { target: { value: '변환이 멈춥니다' } })
    fireEvent.change(screen.getByLabelText('내용'), { target: { value: '같은 오류가 세 번 났습니다' } })
    fireEvent.click(screen.getByRole('button', { name: '보내기' }))

    expect(h.createMutate).toHaveBeenCalledWith(
      { title: '변환이 멈춥니다', body: '같은 오류가 세 번 났습니다', category: 'error', document_id: 'd-1' },
      expect.anything(),
    )
  })

  it('keeps the send button disabled until both title and content have text', () => {
    renderAt('/inquiries/new')

    const send = screen.getByRole('button', { name: '보내기' })
    expect(send).toBeDisabled()
    fireEvent.change(screen.getByLabelText('제목'), { target: { value: '질문' } })
    expect(send).toBeDisabled()
    fireEvent.change(screen.getByLabelText('내용'), { target: { value: '   ' } })
    expect(send).toBeDisabled()
  })

  it('offers an author edit only while the inquiry is open, and no delete after an admin reply', () => {
    h.detail = detailOf()
    const first = renderAt('/inquiries/i-1')
    expect(screen.getByRole('button', { name: '수정' })).toBeInTheDocument()
    first.unmount()

    h.detail = detailOf({ can_edit: false, can_delete: false, has_admin_reply: true, status: 'in_progress' })
    renderAt('/inquiries/i-1')
    expect(screen.queryByRole('button', { name: '수정' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '삭제' })).not.toBeInTheDocument()
  })

  it('gives admins a status control and sends their reply', () => {
    h.role = 'admin'
    h.detail = detailOf({ is_author: false, can_edit: false, can_delete: true })
    renderAt('/inquiries/i-1')

    expect(screen.queryByRole('button', { name: '수정' })).not.toBeInTheDocument()
    expect(screen.getByLabelText('상태')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('답변'), { target: { value: '설정을 바꿔 보세요' } })
    fireEvent.click(screen.getByRole('button', { name: '답변 보내기' }))

    expect(h.replyMutate).toHaveBeenCalledWith({ body: '설정을 바꿔 보세요' }, expect.anything())
  })
})
