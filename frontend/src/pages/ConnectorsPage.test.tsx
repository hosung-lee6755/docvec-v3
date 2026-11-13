import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import ConnectorsPage from './ConnectorsPage'

let role = 'admin'
let directoryLogin = true
const createMutate = vi.fn()
const updateMutate = vi.fn()
const syncMutate = vi.fn()

vi.mock('../store/authStore', () => ({
  useAuthStore: (select: (s: { user: { role: string } }) => unknown) => select({ user: { role } }),
}))

vi.mock('../hooks/useCollections', () => ({
  useCollections: () => ({ data: { items: [{ id: 'col-1', name: '영업 문서' }] } }),
}))

const connector = {
  id: 'c-1', name: '영업 공유', kind: 'smb', acl_mode: 'file_acl', host: 'fs01.corp.local', port: 445, share: 'docs', base_path: '영업',
  username: 'svc-docvec', service_account_sid: null, collection_id: 'col-1', collection_name: '영업 문서',
  level_rules: [{ prefix: 'exec/', level: 'Confidential' }], sync_interval_minutes: 30, max_new_per_run: 200,
  enabled: true, last_sync_at: '2026-11-11T01:00:00Z', last_status: 'partial', held_count: 1, error_count: 0,
  created_at: '2026-11-10T01:00:00Z',
}

vi.mock('../hooks/useConnectors', () => ({
  useConnectors: () => ({ isLoading: false, isError: false, data: [connector] }),
  useConnectorOptions: () => ({
    data: { directory_login: directoryLogin, local_root: '/data/sources', local_folders: ['공용문서'] },
  }),
  useConnector: () => ({
    isLoading: false, isError: false,
    data: {
      ...connector,
      runs: [{ id: 'r-1', started_at: '2026-11-11T01:00:00Z', finished_at: null, status: 'partial',
        counts: { added: 3, held: 1, unchanged: 0 }, error_message: null, triggered_by: null }],
      problem_items: [{ path: 'held/denied.pdf', state: 'held', reason: 'deny_ace', detail: null, last_seen_at: null }],
    },
  }),
  useCreateConnector: () => ({ mutate: createMutate, isPending: false, isError: false }),
  useUpdateConnector: () => ({ mutate: updateMutate, isPending: false, isError: false, isSuccess: false }),
  useDeleteConnector: () => ({ mutate: vi.fn(), isPending: false, isError: false }),
  useSyncConnector: () => ({ mutate: syncMutate, isPending: false, isError: false, isSuccess: false }),
  useTestConnector: () => ({ mutate: vi.fn(), isPending: false, isError: false, data: undefined }),
}))

describe('ConnectorsPage', () => {
  beforeEach(() => {
    role = 'admin'
    directoryLogin = true
    createMutate.mockReset()
    updateMutate.mockReset()
    syncMutate.mockReset()
  })

  it('blocks non-admins', () => {
    role = 'editor'
    render(<ConnectorsPage />)
    expect(screen.getByText('관리자만 접근할 수 있습니다.')).toBeInTheDocument()
  })

  it('shows held files with a readable reason and the run summary', () => {
    render(<ConnectorsPage />)
    fireEvent.click(screen.getByRole('button', { name: /영업 공유/ }))
    expect(screen.getByText('held/denied.pdf')).toBeInTheDocument()
    expect(screen.getByText(/거부\(Deny\) 권한/)).toBeInTheDocument()
    expect(screen.getByText('추가 3, 보류 1')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /지금 동기화/ }))
    expect(syncMutate.mock.calls[0][0]).toBe('c-1')
  })

  it('does not send an empty password when saving settings', () => {
    render(<ConnectorsPage />)
    fireEvent.click(screen.getByRole('button', { name: /영업 공유/ }))
    fireEvent.click(screen.getByRole('button', { name: '설정 저장' }))
    const [{ input }] = updateMutate.mock.calls[0]
    expect(input).not.toHaveProperty('password')
    expect(input.level_rules).toEqual([{ prefix: 'exec/', level: 'Confidential' }])
  })

  it('creates a connector only after the required fields are filled', () => {
    render(<ConnectorsPage />)
    fireEvent.click(screen.getByRole('button', { name: '새 연결' }))
    const submit = screen.getByRole('button', { name: /연결 추가/ })
    expect(submit).toBeDisabled()

    const fill = (label: string, value: string) => fireEvent.change(screen.getByLabelText(label), { target: { value } })
    fill('이름', ' 연구소 ')
    fill('서버 주소', 'fs02')
    fill('공유 이름', 'lab')
    fill('서비스 계정', 'svc')
    fill('비밀번호', 'secret-1')
    fill('넣을 컬렉션', 'col-1')
    fireEvent.click(submit)

    expect(createMutate).toHaveBeenCalledTimes(1)
    expect(createMutate.mock.calls[0][0]).toMatchObject({
      name: '연구소', host: 'fs02', share: 'lab', username: 'svc', password: 'secret-1', collection_id: 'col-1', level_rules: [],
    })
  })

  it('creates a local folder connector without server credentials', () => {
    render(<ConnectorsPage />)
    fireEvent.click(screen.getByRole('button', { name: '새 연결' }))
    fireEvent.click(screen.getByRole('button', { name: '서버 로컬 폴더' }))

    expect(screen.queryByLabelText('서버 주소')).not.toBeInTheDocument()
    expect(screen.getByText(/로컬 폴더에는 파일 권한 정보가 없어/)).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('이름'), { target: { value: '공용' } })
    fireEvent.change(screen.getByLabelText('폴더'), { target: { value: '공용문서' } })
    fireEvent.change(screen.getByLabelText('넣을 컬렉션'), { target: { value: 'col-1' } })
    fireEvent.click(screen.getByRole('button', { name: /연결 추가/ }))

    expect(createMutate.mock.calls[0][0]).toEqual(expect.objectContaining({
      kind: 'local', acl_mode: 'collection_only', base_path: '공용문서',
    }))
    expect(createMutate.mock.calls[0][0]).not.toHaveProperty('password')
  })

  it('warns what each permission basis means', () => {
    directoryLogin = false
    render(<ConnectorsPage />)
    fireEvent.click(screen.getByRole('button', { name: '새 연결' }))

    expect(screen.getByText(/사내 AD 연결이 꺼져 있어/)).toBeInTheDocument()
    fireEvent.click(screen.getByLabelText(/컬렉션 권한만 적용/))
    expect(screen.getByText(/이 컬렉션 구성원 모두에게 열립니다/)).toBeInTheDocument()
  })

  it('sends the permission basis when it is changed in settings', () => {
    render(<ConnectorsPage />)
    fireEvent.click(screen.getByRole('button', { name: /영업 공유/ }))
    fireEvent.click(screen.getByLabelText(/컬렉션 권한만 적용/))
    expect(screen.getByText(/새 기준으로 다시 겁니다/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '설정 저장' }))
    expect(updateMutate.mock.calls[0][0].input.acl_mode).toBe('collection_only')
  })
})
