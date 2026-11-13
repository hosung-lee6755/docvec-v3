import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, within } from '@testing-library/react'
import UsersPage from './UsersPage'

let directoryLogin = false
const createMutateAsync = vi.fn()
const resetMutate = vi.fn()
const linkMutate = vi.fn()
const syncMutate = vi.fn()
let resetData: { temporary_password: string } | undefined

vi.mock('../store/authStore', () => ({
  useAuthStore: (select: (s: { user: { id: string; role: string } }) => unknown) => select({ user: { id: 'me', role: 'admin' } }),
}))

const base = { role: 'viewer', is_active: true, clearance_level: 'Internal', created_at: '2026-11-10T01:00:00Z' }

vi.mock('../hooks/useUsers', () => ({
  useUsers: () => ({
    isLoading: false, isError: false,
    data: {
      items: [
        { ...base, id: 'me', email: 'admin@corp.local', username: '관리자', role: 'admin', auth_source: 'local' },
        { ...base, id: 'u-1', email: 'kim@corp.local', username: '김직원', auth_source: 'local' },
        { ...base, id: 'u-2', email: 'ad@corp.local', username: 'AD직원', auth_source: 'ldap' },
      ],
    },
  }),
  useUpdateUser: () => ({ mutate: vi.fn(), isPending: false, isError: false }),
  useDeleteUser: () => ({ mutateAsync: vi.fn(), isPending: false, isError: false }),
}))

vi.mock('../hooks/useAccounts', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../hooks/useAccounts')>()
  return {
    ...actual,
    useAuthOptions: () => ({ data: { self_signup_enabled: false, admin_code_signup: true, directory_login: directoryLogin } }),
    useCreateAccount: () => ({ mutateAsync: createMutateAsync, isPending: false, isError: false, reset: vi.fn() }),
    useResetPassword: () => ({ mutate: resetMutate, data: resetData, isPending: false, isError: false, reset: vi.fn() }),
    useImportAccounts: () => ({ mutateAsync: vi.fn(), isPending: false, isError: false, error: null, reset: vi.fn() }),
    useLinkDirectory: () => ({ mutate: linkMutate, isPending: false, isError: false }),
    useSyncDirectory: () => ({ mutate: syncMutate, isPending: false, isError: false, isSuccess: false }),
  }
})

describe('UsersPage account management', () => {
  beforeEach(() => {
    directoryLogin = false
    resetData = undefined
    createMutateAsync.mockReset()
    resetMutate.mockReset()
    linkMutate.mockReset()
    syncMutate.mockReset()
  })

  it('creates an account and shows the temporary password once', async () => {
    createMutateAsync.mockResolvedValue({
      user: { ...base, id: 'u-3', email: 'new@corp.local', username: '새직원' },
      temporary_password: 'Temp1234abcd',
    })
    render(<UsersPage />)

    fireEvent.click(screen.getByRole('button', { name: '계정 만들기' }))
    fireEvent.change(screen.getByLabelText('이메일(로그인 아이디)'), { target: { value: ' new@corp.local ' } })
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: '계정 만들기' }))

    expect(await screen.findByLabelText('new@corp.local 임시 비밀번호')).toHaveTextContent('Temp1234abcd')
    expect(createMutateAsync).toHaveBeenCalledWith(expect.objectContaining({ email: 'new@corp.local', role: 'viewer' }))
  })

  it('offers password reset only for local accounts other than yourself, and warns before resetting', () => {
    render(<UsersPage />)

    expect(screen.queryByRole('button', { name: 'admin@corp.local 비밀번호 초기화' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'ad@corp.local 비밀번호 초기화' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'kim@corp.local 비밀번호 초기화' }))

    expect(screen.getByText(/외부 에이전트 토큰도 모두 회수됩니다/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '초기화' }))
    expect(resetMutate).toHaveBeenCalledWith('u-1')
  })

  it('hides account creation while directory login is on', () => {
    directoryLogin = true
    render(<UsersPage />)

    expect(screen.queryByRole('button', { name: '계정 만들기' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'CSV로 일괄 등록' })).not.toBeInTheDocument()
    expect(screen.getByText(/사내 계정\(AD\) 로그인을 쓰고 있습니다/)).toBeInTheDocument()
  })

  it('with directory login on, offers AD sync and converting local accounts after a warning', () => {
    directoryLogin = true
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    render(<UsersPage />)

    fireEvent.click(screen.getByRole('button', { name: '지금 AD와 동기화' }))
    expect(syncMutate).toHaveBeenCalled()
    expect(screen.queryByRole('button', { name: 'kim@corp.local 비밀번호 초기화' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'kim@corp.local AD 계정으로 전환' }))
    expect(confirm.mock.calls[0][0]).toMatch(/외부 에이전트 토큰도 모두 끊깁니다/)
    expect(linkMutate).toHaveBeenCalledWith('u-1')
    confirm.mockRestore()
  })
})
