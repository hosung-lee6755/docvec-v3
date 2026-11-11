import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import AccessTokenSection from './AccessTokenSection'
import type { IssuedToken, MyTokens } from '../../hooks/useAccessTokens'

const createMutate = vi.fn()
const revokeMutate = vi.fn()
let tokens: MyTokens

const activeToken = {
  id: 't-1', name: '노트북 Claude', token_prefix: 'dvp_AbCd', created_at: '2026-11-10T01:00:00Z',
  expires_at: '2027-02-08T01:00:00Z', last_used_at: null, revoked_at: null, status: 'active' as const,
}

vi.mock('../../hooks/useAccessTokens', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../hooks/useAccessTokens')>()
  return {
    ...actual,
    useMyAccessTokens: () => ({ isLoading: false, isError: false, data: tokens }),
    useCreateAccessToken: () => ({ mutate: createMutate, isPending: false, isError: false }),
    useRevokeMyAccessToken: () => ({ mutate: revokeMutate, isPending: false, isError: false }),
  }
})

describe('AccessTokenSection', () => {
  beforeEach(() => {
    createMutate.mockReset()
    revokeMutate.mockReset()
    tokens = { mcp_enabled: true, mcp_path: '/api/v1/mcp', default_days: 90, max_days: 365, items: [activeToken] }
  })

  it('creates a token and shows the raw value with a connect command exactly once', () => {
    const issued: IssuedToken = { ...activeToken, id: 't-2', name: '새 토큰', token: 'dvp_secret-raw-token' }
    createMutate.mockImplementation((_input, opts) => opts.onSuccess(issued))
    render(<AccessTokenSection />)

    fireEvent.change(screen.getByLabelText('이름'), { target: { value: '  새 토큰 ' } })
    fireEvent.click(screen.getByRole('button', { name: '토큰 만들기' }))

    expect(createMutate).toHaveBeenCalledWith({ name: '새 토큰', expires_in_days: 90 }, expect.anything())
    expect(screen.getByLabelText('발급된 토큰')).toHaveTextContent('dvp_secret-raw-token')
    expect(screen.getByText(/claude mcp add --transport http docvec .*\/api\/v1\/mcp/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '복사했습니다. 닫기' }))
    expect(screen.queryByText(/dvp_secret-raw-token/)).not.toBeInTheDocument()
  })

  it('does not allow an expiry beyond the server limit', () => {
    render(<AccessTokenSection />)
    fireEvent.change(screen.getByLabelText('이름'), { target: { value: 'x' } })
    fireEvent.change(screen.getByLabelText('유효 기간(일)'), { target: { value: '400' } })
    expect(screen.getByRole('button', { name: '토큰 만들기' })).toBeDisabled()
  })

  it('revokes an active token after confirmation', () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    render(<AccessTokenSection />)
    fireEvent.click(screen.getByRole('button', { name: '노트북 Claude 회수' }))
    expect(revokeMutate).toHaveBeenCalledWith('t-1')
  })

  it('hides the create form when MCP is turned off', () => {
    tokens = { ...tokens, mcp_enabled: false }
    render(<AccessTokenSection />)
    expect(screen.queryByRole('button', { name: '토큰 만들기' })).not.toBeInTheDocument()
    expect(screen.getByText(/새 토큰을 만들 수 없습니다/)).toBeInTheDocument()
  })
})
