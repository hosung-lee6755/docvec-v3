import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import LoginPage from './LoginPage'
import type { AuthOptions } from '../hooks/useAccounts'

let options: AuthOptions
vi.mock('../hooks/useAccounts', () => ({
  useAuthOptions: () => ({ data: options }),
}))

function renderPage() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter><LoginPage /></MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('LoginPage signup hint', () => {
  beforeEach(() => {
    options = { self_signup_enabled: false, admin_code_signup: false, directory_login: false }
  })

  it('shows the signup link only when self signup is on', () => {
    options.self_signup_enabled = true
    renderPage()
    expect(screen.getByRole('link', { name: '회원가입' })).toHaveAttribute('href', '/register')
  })

  it('tells users that accounts are issued by an admin when signup is off', () => {
    renderPage()
    expect(screen.queryByRole('link', { name: '회원가입' })).not.toBeInTheDocument()
    expect(screen.getByText(/계정은 관리자가 발급합니다/)).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: '관리자 초대 코드로 가입' })).not.toBeInTheDocument()
  })

  it('keeps the admin code route for bootstrapping the first admin', () => {
    options.admin_code_signup = true
    renderPage()
    expect(screen.getByRole('link', { name: '관리자 초대 코드로 가입' })).toBeInTheDocument()
  })
})
