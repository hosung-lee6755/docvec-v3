import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import ChangePasswordPage from './ChangePasswordPage'

const updateUser = vi.fn()
const mutate = vi.fn()
let mustChange = true

vi.mock('../store/authStore', () => ({
  useAuthStore: (select: (s: object) => unknown) => select({
    isAuthenticated: true,
    user: { id: 'u', email: 'kim@corp.local', must_change_password: mustChange },
    updateUser,
    clearAuth: vi.fn(),
  }),
}))

vi.mock('../hooks/useProfile', () => ({
  useChangePassword: () => ({ mutate, isPending: false, isError: false }),
}))

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/change-password']}>
      <Routes>
        <Route path="/change-password" element={<ChangePasswordPage />} />
        <Route path="/" element={<p>홈 화면</p>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('ChangePasswordPage', () => {
  beforeEach(() => {
    mustChange = true
    mutate.mockReset()
    updateUser.mockReset()
  })

  it('changes the temporary password and clears the flag', () => {
    mutate.mockImplementation((_vars, options) => options.onSuccess())
    renderPage()

    fireEvent.change(screen.getByLabelText('임시 비밀번호'), { target: { value: 'Temp1234abcd' } })
    fireEvent.change(screen.getByLabelText('새 비밀번호'), { target: { value: 'my-new-secret' } })
    fireEvent.change(screen.getByLabelText('새 비밀번호 확인'), { target: { value: 'my-new-secret' } })
    fireEvent.click(screen.getByRole('button', { name: '비밀번호 바꾸고 시작하기' }))

    expect(mutate).toHaveBeenCalledWith({ currentPassword: 'Temp1234abcd', newPassword: 'my-new-secret' }, expect.anything())
    expect(updateUser).toHaveBeenCalledWith({ must_change_password: false })
  })

  it('refuses to reuse the temporary password', () => {
    renderPage()

    fireEvent.change(screen.getByLabelText('임시 비밀번호'), { target: { value: 'Temp1234abcd' } })
    fireEvent.change(screen.getByLabelText('새 비밀번호'), { target: { value: 'Temp1234abcd' } })

    expect(screen.getByText('임시 비밀번호와 다른 비밀번호를 정하세요.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '비밀번호 바꾸고 시작하기' })).toBeDisabled()
  })

  it('sends users without a temporary password home', () => {
    mustChange = false
    renderPage()
    expect(screen.getByText('홈 화면')).toBeInTheDocument()
  })
})
