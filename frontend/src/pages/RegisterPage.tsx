import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import axios from 'axios'
import { useAuthStore } from '../store/authStore'
import { Alert, Button, Field, Input } from '../components/ui'
import { describeError } from '../lib/apiError'
import '../styles/screens/user.css'

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
    <div className="user-auth">
      <div className="user-auth__card">
        <div className="user-auth__brand">
          <span className="user-auth__logo" aria-hidden="true">DV</span>
          <h1 className="user-auth__name">DocVec</h1>
          <p className="user-auth__subtitle">새 계정 만들기</p>
        </div>
        <form className="user-auth__form" onSubmit={(e) => { e.preventDefault(); registerMutation.mutate() }}>
          <Field label="이메일">
            {(id) => (
              <Input
                id={id}
                type="email" value={email} onChange={(e) => setEmail(e.target.value)} required
                placeholder="user@example.com"
              />
            )}
          </Field>
          <Field label="사용자 이름">
            {(id) => (
              <Input
                id={id}
                type="text" value={username} onChange={(e) => setUsername(e.target.value)} required
                placeholder="예: 홍길동"
              />
            )}
          </Field>
          <Field label="비밀번호">
            {(id) => (
              <Input
                id={id}
                type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={8}
                placeholder="8자 이상"
              />
            )}
          </Field>

          <div>
            <button type="button" className="ds-link-btn" aria-expanded={showAdminCode}
              onClick={() => setShowAdminCode((v) => !v)}>
              {showAdminCode ? '관리자 코드 숨기기' : '관리자 코드가 있으신가요?'}
            </button>
            {showAdminCode && (
              <div className="user-auth__admin-code">
                <Field label="관리자 초대 코드">
                  {(id) => (
                    <Input
                      id={id}
                      type="text" value={adminCode} onChange={(e) => setAdminCode(e.target.value)}
                      placeholder="관리자 초대 코드"
                    />
                  )}
                </Field>
              </div>
            )}
          </div>

          {registerMutation.isError && (
            <Alert tone="danger">
              {axios.isAxiosError(registerMutation.error) && registerMutation.error.response?.status === 409
                ? '이미 사용 중인 이메일입니다.'
                : describeError(registerMutation.error, '회원가입하지 못했습니다.')}
            </Alert>
          )}
          <Button type="submit" variant="primary" isBlock disabled={registerMutation.isPending}>
            {registerMutation.isPending ? '가입 중...' : '회원가입'}
          </Button>
        </form>
        <p className="user-auth__footer">
          이미 계정이 있으신가요?{' '}
          <Link to="/login" className="user-auth__link">로그인</Link>
        </p>
      </div>
    </div>
  )
}
