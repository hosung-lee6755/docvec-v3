import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import axios from 'axios'
import { useAuthStore } from '../store/authStore'

export default function RegisterPage() {
  const [email, setEmail] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showAdminCode, setShowAdminCode] = useState(false)
  const [adminCode, setAdminCode] = useState('')
  const navigate = useNavigate()
  const setAuth = useAuthStore((s) => s.setAuth)

  const registerMutation = useMutation({
    mutationFn: async () => {
      const { data } = await axios.post('/api/v1/auth/register', {
        email, username, password, admin_code: adminCode || undefined,
      })
      return data
    },
    onSuccess: (data) => {
      setAuth(data.user, data.access_token)
      navigate('/', { replace: true })
    },
  })

  return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{
        background: 'var(--color-surface)', border: '1px solid var(--color-border)',
        borderRadius: 'var(--radius-lg)', padding: 'var(--space-8)', width: 360,
      }}>
        <h1 style={{ fontSize: 24, fontWeight: 700, marginBottom: 'var(--space-6)', color: 'var(--color-text)' }}>DocVec</h1>
        <form onSubmit={(e) => { e.preventDefault(); registerMutation.mutate() }}>
          <div className="form-group" style={{ marginBottom: 'var(--space-4)' }}>
            <div className="form-tit" style={{ color: 'var(--color-text-muted)' }}>
              <label htmlFor="register_email">이메일</label>
            </div>
            <div className="form-conts">
              <input
                id="register_email"
                type="email" value={email} onChange={(e) => setEmail(e.target.value)} required
                placeholder="user@example.com"
                className="krds-input"
                style={{ width: '100%', boxSizing: 'border-box' }}
              />
            </div>
          </div>
          <div className="form-group" style={{ marginBottom: 'var(--space-4)' }}>
            <div className="form-tit" style={{ color: 'var(--color-text-muted)' }}>
              <label htmlFor="register_username">사용자 이름</label>
            </div>
            <div className="form-conts">
              <input
                id="register_username"
                type="text" value={username} onChange={(e) => setUsername(e.target.value)} required
                placeholder="예: 홍길동"
                className="krds-input"
                style={{ width: '100%', boxSizing: 'border-box' }}
              />
            </div>
          </div>
          <div className="form-group" style={{ marginBottom: 'var(--space-6)' }}>
            <div className="form-tit" style={{ color: 'var(--color-text-muted)' }}>
              <label htmlFor="register_password">비밀번호</label>
            </div>
            <div className="form-conts">
              <input
                id="register_password"
                type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={8}
                placeholder="8자 이상"
                className="krds-input"
                style={{ width: '100%', boxSizing: 'border-box' }}
              />
            </div>
          </div>
          <div style={{ marginBottom: 'var(--space-6)' }}>
            <button
              type="button"
              onClick={() => setShowAdminCode((v) => !v)}
              style={{
                background: 'none', border: 'none', padding: 0, cursor: 'pointer',
                fontSize: 12, color: 'var(--color-text-muted)', textDecoration: 'underline',
              }}
            >
              {showAdminCode ? '관리자 코드 숨기기' : '관리자 코드가 있으신가요?'}
            </button>
            {showAdminCode && (
              <div className="form-group" style={{ marginTop: 'var(--space-2)' }}>
                <div className="form-conts">
                  <input
                    id="register_admin_code"
                    type="text" value={adminCode} onChange={(e) => setAdminCode(e.target.value)}
                    placeholder="관리자 초대 코드"
                    className="krds-input"
                    style={{ width: '100%', boxSizing: 'border-box' }}
                  />
                </div>
              </div>
            )}
          </div>
          {registerMutation.isError && (
            <p style={{ color: 'var(--color-danger)', fontSize: 12, marginBottom: 'var(--space-4)' }}>
              {axios.isAxiosError(registerMutation.error) && registerMutation.error.response?.status === 409
                ? '이미 사용 중인 이메일입니다.'
                : '회원가입 실패. 다시 시도해주세요.'}
            </p>
          )}
          <button
            type="submit" disabled={registerMutation.isPending}
            className="krds-btn medium primary"
            style={{ width: '100%', justifyContent: 'center' }}
          >
            {registerMutation.isPending ? '가입 중...' : '회원가입'}
          </button>
        </form>
        <p style={{ marginTop: 'var(--space-4)', textAlign: 'center', fontSize: 13, color: 'var(--color-text-muted)' }}>
          이미 계정이 있으신가요?{' '}
          <Link to="/login" style={{ color: 'var(--color-accent)', textDecoration: 'none' }}>로그인</Link>
        </p>
      </div>
    </div>
  )
}
