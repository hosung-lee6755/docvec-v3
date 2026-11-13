import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import AccessTokensPage from './AccessTokensPage'

let role = 'admin'
const revokeMutate = vi.fn()

vi.mock('../store/authStore', () => ({
  useAuthStore: (select: (s: { user: { role: string } }) => unknown) => select({ user: { role } }),
}))

const base = {
  token_prefix: 'dvp_AbCd', created_at: '2026-11-10T01:00:00Z', expires_at: '2027-02-08T01:00:00Z',
  last_used_at: null, revoked_at: null, user_id: 'u-1', username: '김직원', email: 'kim@corp.local',
}

vi.mock('../hooks/useAccessTokens', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../hooks/useAccessTokens')>()
  return {
    ...actual,
    useAllAccessTokens: () => ({
      isLoading: false, isError: false,
      data: {
        mcp_enabled: true,
        items: [
          { ...base, id: 't-1', name: '노트북', status: 'active' },
          { ...base, id: 't-2', name: '옛 토큰', status: 'revoked', revoked_at: '2026-11-10T02:00:00Z' },
        ],
      },
    }),
    useRevokeAnyAccessToken: () => ({ mutate: revokeMutate, isPending: false, isError: false }),
  }
})

describe('AccessTokensPage', () => {
  beforeEach(() => {
    role = 'admin'
    revokeMutate.mockReset()
  })

  it('lists every token and only offers revoke for active ones', () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    render(<MemoryRouter><AccessTokensPage /></MemoryRouter>)

    expect(screen.getByText('회수됨')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '김직원의 옛 토큰 회수' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '김직원의 노트북 회수' }))
    expect(revokeMutate).toHaveBeenCalledWith('t-1')
  })

  it('tells admins that tokens are issued from each user account settings', () => {
    render(<MemoryRouter><AccessTokensPage /></MemoryRouter>)
    expect(screen.getByText(/발급은 계정 설정 > 외부 에이전트에서 합니다/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '계정 설정 > 외부 에이전트로 가기' })).toHaveAttribute('href', '/settings?tab=agent')
  })

  it('is closed to non-admins', () => {
    role = 'viewer'
    render(<MemoryRouter><AccessTokensPage /></MemoryRouter>)
    expect(screen.getByText('관리자만 접근할 수 있습니다.')).toBeInTheDocument()
  })
})
