import { useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { useChangePassword } from '../hooks/useProfile'
import { useAuthStore } from '../store/authStore'
import { Alert, Button, ErrorAlert, Field, Input } from '../components/ui'
import '../styles/screens/user.css'

const MIN_PASSWORD_LENGTH = 8

/** 관리자가 발급하거나 초기화한 임시 비밀번호를 자기 비밀번호로 바꾸는 화면. 바꾸기 전에는 다른 화면을 쓸 수 없다. */
export default function ChangePasswordPage() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  const user = useAuthStore((s) => s.user)
  const updateUser = useAuthStore((s) => s.updateUser)
  const clearAuth = useAuthStore((s) => s.clearAuth)
  const navigate = useNavigate()
  const changePassword = useChangePassword()
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')

  if (!isAuthenticated) return <Navigate to="/login" replace />
  if (!user?.must_change_password) return <Navigate to="/" replace />

  const tooShort = newPassword.length > 0 && newPassword.length < MIN_PASSWORD_LENGTH
  const mismatch = confirmPassword.length > 0 && newPassword !== confirmPassword
  const sameAsTemporary = newPassword.length > 0 && newPassword === currentPassword
  const canSubmit = Boolean(currentPassword && newPassword && confirmPassword) && !tooShort && !mismatch && !sameAsTemporary
  const newPasswordError = tooShort
    ? `${MIN_PASSWORD_LENGTH}자 이상이어야 합니다.`
    : sameAsTemporary ? '임시 비밀번호와 다른 비밀번호를 정하세요.' : undefined

  const handleSubmit = () => {
    if (!canSubmit) return
    changePassword.mutate(
      { currentPassword, newPassword },
      {
        onSuccess: () => {
          updateUser({ must_change_password: false })
          navigate('/', { replace: true })
        },
      },
    )
  }

  return (
    <div className="user-auth">
      <div className="user-auth__card">
        <div className="user-auth__brand">
          <span className="user-auth__logo" aria-hidden="true">DV</span>
          <h1 className="user-auth__name">새 비밀번호 정하기</h1>
          <p className="user-auth__subtitle">{user.email}</p>
        </div>
        <form className="user-auth__form" onSubmit={(e) => { e.preventDefault(); handleSubmit() }}>
          <Alert tone="info">
            관리자가 발급한 임시 비밀번호로 로그인했습니다. 계속하려면 본인만 아는 새 비밀번호를 정하세요.
          </Alert>
          <Field label="임시 비밀번호">
            {(id) => (
              <Input id={id} type="password" autoComplete="current-password" required
                value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} />
            )}
          </Field>
          <Field label="새 비밀번호" hint={`${MIN_PASSWORD_LENGTH}자 이상`} error={newPasswordError}>
            {(id) => (
              <Input id={id} type="password" autoComplete="new-password" required
                value={newPassword} onChange={(e) => setNewPassword(e.target.value)} />
            )}
          </Field>
          <Field label="새 비밀번호 확인" error={mismatch ? '새 비밀번호와 같지 않습니다.' : undefined}>
            {(id) => (
              <Input id={id} type="password" autoComplete="new-password" required
                value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} />
            )}
          </Field>
          {changePassword.isError && (
            <ErrorAlert error={changePassword.error} message="비밀번호를 바꾸지 못했습니다. 임시 비밀번호를 확인하세요." />
          )}
          <Button type="submit" variant="primary" isBlock disabled={!canSubmit || changePassword.isPending}>
            {changePassword.isPending ? '바꾸는 중...' : '비밀번호 바꾸고 시작하기'}
          </Button>
        </form>
        <p className="user-auth__footer">
          <button type="button" className="ds-link-btn" onClick={clearAuth}>다른 계정으로 로그인</button>
        </p>
      </div>
    </div>
  )
}
