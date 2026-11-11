import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import AccessPanel from './AccessPanel'

const mutate = vi.fn()
let aclState: Record<string, unknown>

vi.mock('../../hooks/useAccess', async () => {
  const actual = await vi.importActual<typeof import('../../hooks/useAccess')>('../../hooks/useAccess')
  return {
    ...actual,
    useDocumentAcl: () => aclState,
    useGroups: () => ({ data: { items: [{ id: 'g-1', name: '품질팀', description: null, member_count: 2, created_at: '' }] } }),
    useReplaceDocumentAcl: () => ({ mutate, isPending: false, isError: false }),
  }
})

vi.mock('../../hooks/useCollections', () => ({
  useCollectionMembers: () => ({ data: { items: [{ user_id: 'u-2', email: 'b@x', username: 'bob', role: 'viewer', created_at: null }] } }),
}))

const renderPanel = () =>
  render(<AccessPanel documentId="doc-1" collectionId="col-1" securityLevel={null} />)

describe('AccessPanel', () => {
  beforeEach(() => {
    mutate.mockReset()
  })

  it('renders nothing when the user cannot edit the document (403)', () => {
    aclState = { isError: true, error: { response: { status: 403 } } }
    const { container } = renderPanel()
    expect(container).toBeEmptyDOMElement()
  })

  it('shows unrestricted state with the inherited effective level', () => {
    aclState = {
      isError: false,
      data: { document_id: 'doc-1', security_level: null, effective_security_level: 'Confidential', restricted: false, entries: [] },
    }
    renderPanel()
    expect(screen.getByText(/제한 없음/)).toBeInTheDocument()
    expect(screen.getByText('대외비')).toBeInTheDocument()
    expect(screen.getByText(/컬렉션 기본값/)).toBeInTheDocument()
  })

  it('adds a group by replacing the whole list', () => {
    aclState = {
      isError: false,
      data: {
        document_id: 'doc-1', security_level: 'Internal', effective_security_level: 'Internal', restricted: true,
        entries: [{ principal_type: 'user', principal_id: 'u-2', display_name: 'bob' }],
      },
    }
    renderPanel()
    fireEvent.change(screen.getByLabelText('허용 목록에 추가할 사용자 또는 그룹'), { target: { value: 'group:g-1' } })
    fireEvent.click(screen.getByRole('button', { name: '추가' }))
    expect(mutate).toHaveBeenCalledWith({
      documentId: 'doc-1',
      entries: [
        { principal_type: 'user', principal_id: 'u-2' },
        { principal_type: 'group', principal_id: 'g-1' },
      ],
    })
  })

  it('labels deleted principals and lifts the restriction with an empty list', () => {
    aclState = {
      isError: false,
      data: {
        document_id: 'doc-1', security_level: null, effective_security_level: 'Public', restricted: true,
        entries: [{ principal_type: 'group', principal_id: 'g-9', display_name: null }],
      },
    }
    renderPanel()
    expect(screen.getByText(/삭제된 그룹/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '제한 해제' }))
    expect(mutate).toHaveBeenCalledWith({ documentId: 'doc-1', entries: [] })
  })

  it('blocks relaxing actions for editors who are not the uploader or collection owner', () => {
    aclState = {
      isError: false,
      data: {
        document_id: 'doc-1', security_level: 'Internal', effective_security_level: 'Internal', restricted: true,
        can_relax: false,
        entries: [{ principal_type: 'user', principal_id: 'u-2', display_name: 'bob' }],
      },
    }
    renderPanel()
    expect(screen.getByRole('button', { name: '제한 해제' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'bob 허용 해제' })).toBeDisabled()
    fireEvent.change(screen.getByLabelText('허용 목록에 추가할 사용자 또는 그룹'), { target: { value: 'group:g-1' } })
    expect(screen.getByRole('button', { name: '추가' })).toBeDisabled()
    expect(screen.getByText(/업로더나 컬렉션 소유자만/)).toBeInTheDocument()
  })
})
