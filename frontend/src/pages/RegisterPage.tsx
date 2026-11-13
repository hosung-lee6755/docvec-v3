import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import axios from 'axios'
import { useAuthStore } from '../store/authStore'
import { useAuthOptions } from '../hooks/useAccounts'
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
  const { data: options } = useAuthOptions()
  // 회원가입을 끈 회사에서는 첫 관리자만 초대 코드로 가입한다
  const isAdminCodeOnly = options !== undefined && !options.self_signup_enabled
  const isClosed = isAdminCodeOnly && !options.admin_code_signup
  const isAdminCodeShown = showAdminCode || isAdminCodeOnly

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
          <p className="user-auth__subtitle">{isAdminCodeOnly ? '관리자 계정 만들기' : '새 계정 만들기'}</p>
        </div>
        {isClosed ? (
          <Alert tone="info">
            이 시스템은 회원가입을 받지 않습니다. 계정은 관리자가 사용자 관리 화면에서 발급합니다.
          </Alert>
        ) : (
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

          {isAdminCodeOnly && (
            <Alert tone="info">
              일반 회원가입은 받지 않습니다. 처음 관리자 계정을 만들 때만 서버에 설정한 관리자 초대 코드로 가입할 수 있습니다.
            </Alert>
          )}
          <div>
            {!isAdminCodeOnly && (
              <button type="button" className="ds-link-btn" aria-expanded={showAdminCode}
                onClick={() => setShowAdminCode((v) => !v)}>
                {showAdminCode ? '관리자 코드 숨기기' : '관리자 코드가 있으신가요?'}
              </button>
            )}
            {isAdminCodeShown && (
              <div className="user-auth__admin-code">
                <Field label="관리자 초대 코드">
                  {(id) => (
                    <Input
                      id={id}
                      type="text" value={adminCode} onChange={(e) => setAdminCode(e.target.value)} required={isAdminCodeOnly}
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
                : axios.isAxiosError(registerMutation.error) && registerMutation.error.response?.status === 403
                ? describeError(registerMutation.error, '관리자 초대 코드가 맞지 않습니다.')
                : describeError(registerMutation.error, '회원가입하지 못했습니다.')}
            </Alert>
          )}
          <Button type="submit" variant="primary" isBlock disabled={registerMutation.isPending}>
            {registerMutation.isPending ? '가입 중...' : '회원가입'}
          </Button>
        </form>
        )}
        <p className="user-auth__footer">
          이미 계정이 있으신가요?{' '}
          <Link to="/login" className="user-auth__link">로그인</Link>
        </p>
      </div>
    </div>
  )
}
