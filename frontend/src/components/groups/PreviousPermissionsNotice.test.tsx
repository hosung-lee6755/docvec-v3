import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import PreviousPermissionsNotice from './PreviousPermissionsNotice'

const inherit = vi.fn()
const dismiss = vi.fn()
let preview: unknown

vi.mock('../../hooks/useAccess', () => ({
  usePreviousPermissions: () => ({ data: preview, isLoading: false, isError: false, error: null }),
  useInheritPreviousPermissions: () => ({ mutate: inherit, isPending: false, error: null }),
  useDismissPreviousPermissions: () => ({ mutate: dismiss, isPending: false, error: null }),
}))

function renderNotice() {
  return render(<MemoryRouter><PreviousPermissionsNotice groupId="g-1" /></MemoryRouter>)
}

describe('PreviousPermissionsNotice', () => {
  beforeEach(() => {
    inherit.mockReset()
    dismiss.mockReset()
    preview = {
      previous_group_id: 'old', document_count: 3, connector_document_count: 1,
      documents: [{ id: 'd1', title: '영업 계획' }, { id: 'd2', title: '단가표' }],
    }
  })

  it('lists the documents and inherits on request', () => {
    renderNotice()
    expect(screen.getByText(/예전 그룹에 열어 둔 문서 3건/)).toBeInTheDocument()
    expect(screen.getByText(/파일 서버에서 온 문서 1건/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '영업 계획' })).toHaveAttribute('href', '/documents/d1')
    expect(screen.getByText('외 1건')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '문서 권한 이어받기' }))
    expect(inherit).toHaveBeenCalledWith('g-1')
  })

  it('asks for confirmation before dismissing', () => {
    renderNotice()
    fireEvent.click(screen.getByRole('button', { name: '이어받지 않기' }))
    expect(dismiss).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: '이어받지 않기 확인' }))
    expect(dismiss).toHaveBeenCalledWith('g-1')
  })

  it('renders nothing once there is nothing to inherit', () => {
    preview = { previous_group_id: null, document_count: 0, connector_document_count: 0, documents: [] }
    const { container } = renderNotice()
    expect(container).toBeEmptyDOMElement()
  })
})
