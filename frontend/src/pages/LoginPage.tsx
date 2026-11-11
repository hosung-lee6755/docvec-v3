import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import axios from 'axios'
import { useAuthStore } from '../store/authStore'

const GENERIC_LOGIN_ERROR = "로그인하지 못했습니다. 아이디(이메일)와 비밀번호를 확인하세요."

// 사내 계정 서버 장애(503)와 같은 이메일의 로컬 계정 충돌(409)은 서버 안내를 그대로 보여 준다.
function loginErrorMessage(error: unknown): string {
  if (axios.isAxiosError(error) && [409, 503].includes(error.response?.status ?? 0)) {
    const detail = error.response?.data?.detail
    if (typeof detail === "string") return detail
  }
  return GENERIC_LOGIN_ERROR
}

export default function LoginPage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const navigate = useNavigate()
  const setAuth = useAuthStore((s) => s.setAuth)

  const loginMutation = useMutation({
    mutationFn: async () => {
      const { data } = await axios.post('/api/v1/auth/login', { email, password })
      return data
    },
    onSuccess: (data) => {
      setAuth(data.user, data.access_token)
      navigate('/', { replace: true })
    },
  })

  return (
    <div style={{
      minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
    }}>
      <div style={{
        background: 'var(--color-surface)', border: '1px solid var(--color-border)',
        borderRadius: 'var(--radius-lg)', padding: 'var(--space-8)', width: 360,
      }}>
        <h1 style={{ fontSize: 24, fontWeight: 700, marginBottom: 'var(--space-6)', color: 'var(--color-text)' }}>DocVec</h1>
        <form onSubmit={(e) => { e.preventDefault(); loginMutation.mutate() }}>
          <div className="form-group" style={{ marginBottom: 'var(--space-4)' }}>
            <div className="form-tit" style={{ color: 'var(--color-text-muted)' }}>
              <label htmlFor="login_email">아이디 또는 이메일</label>
            </div>
            <div className="form-conts">
              <input
                id="login_email"
                type="text" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required
                placeholder="사내 계정 아이디 또는 user@example.com"
                className="krds-input"
                style={{ width: '100%', boxSizing: 'border-box' }}
              />
            </div>
          </div>
          <div className="form-group" style={{ marginBottom: 'var(--space-6)' }}>
            <div className="form-tit" style={{ color: 'var(--color-text-muted)' }}>
              <label htmlFor="login_password">비밀번호</label>
            </div>
            <div className="form-conts">
              <input
                id="login_password"
                type="password" value={password} onChange={(e) => setPassword(e.target.value)} required
                className="krds-input"
                style={{ width: '100%', boxSizing: 'border-box' }}
              />
            </div>
          </div>
          {loginMutation.isError && (
            <p role="alert" style={{ color: 'var(--color-danger)', fontSize: 12, marginBottom: 'var(--space-4)' }}>
              {loginErrorMessage(loginMutation.error)}
            </p>
          )}
          <button
            type="submit" disabled={loginMutation.isPending}
            className="krds-btn medium primary"
            style={{ width: '100%', justifyContent: 'center' }}
          >
            {loginMutation.isPending ? '로그인 중...' : '로그인'}
          </button>
        </form>
        <p style={{ marginTop: 'var(--space-4)', textAlign: 'center', fontSize: 13, color: 'var(--color-text-muted)' }}>
          계정이 없으신가요?{' '}
          <Link to="/register" style={{ color: 'var(--color-accent)', textDecoration: 'none' }}>회원가입</Link>
        </p>
      </div>
    </div>
  )
}
