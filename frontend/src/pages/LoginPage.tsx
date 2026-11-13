import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import axios from 'axios'
import { useAuthStore } from '../store/authStore'
import { useAuthOptions } from '../hooks/useAccounts'
import type { AuthOptions } from '../hooks/useAccounts'
import { Alert, Button, Field, Input } from '../components/ui'
import { describeError } from '../lib/apiError'
import '../styles/screens/user.css'

const GENERIC_LOGIN_ERROR = "로그인하지 못했습니다. 아이디(이메일)와 비밀번호를 확인하세요."

// 사내 계정 서버 장애(503)와 같은 이메일의 로컬 계정 충돌(409)은 서버 안내를 그대로 보여 준다.
function loginErrorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const status = error.response?.status ?? 0
    if ([409, 503].includes(status)) {
      const detail = error.response?.data?.detail
      if (typeof detail === "string") return detail
    }
    // 아이디·비밀번호 문제는 어느 쪽이 틀렸는지 알리지 않는다(계정 존재 여부 노출 방지)
    if (status === 400 || status === 401 || status === 422) return GENERIC_LOGIN_ERROR
  }
  // 서버에 닿지 못했거나 서버 쪽 문제면 그 원인을 그대로 알린다
  return describeError(error, '로그인하지 못했습니다.')
}

/** 가입 정책에 맞는 안내. 회원가입을 막은 회사에서는 링크 대신 계정 발급 안내를 보인다. */
function SignupHint({ options }: { options: AuthOptions | undefined }) {
  if (!options) return null
  if (options.directory_login) {
    return <p className="user-auth__footer">사내 계정(AD) 아이디와 비밀번호로 로그인합니다.</p>
  }
  if (options.self_signup_enabled) {
    return (
      <p className="user-auth__footer">
        계정이 없으신가요?{' '}
        <Link to="/register" className="user-auth__link">회원가입</Link>
      </p>
    )
  }
  return (
    <p className="user-auth__footer">
      계정은 관리자가 발급합니다. 계정이 없으면 관리자에게 요청하세요.
      {options.admin_code_signup && (
        <>
          {' '}
          <Link to="/register" className="user-auth__link">관리자 초대 코드로 가입</Link>
        </>
      )}
    </p>
  )
}

export default function LoginPage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const navigate = useNavigate()
  const setAuth = useAuthStore((s) => s.setAuth)
  const { data: options } = useAuthOptions()

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
    <div className="user-auth">
      <div className="user-auth__card">
        <div className="user-auth__brand">
          <span className="user-auth__logo" aria-hidden="true">DV</span>
          <h1 className="user-auth__name">DocVec</h1>
          <p className="user-auth__subtitle">계정에 로그인</p>
        </div>
        <form className="user-auth__form" onSubmit={(e) => { e.preventDefault(); loginMutation.mutate() }}>
          <Field label="아이디 또는 이메일">
            {(id) => (
              <Input
                id={id}
                type="text" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required
                placeholder="사내 계정 아이디 또는 user@example.com"
              />
            )}
          </Field>
          <Field label="비밀번호">
            {(id) => (
              <Input
                id={id}
                type="password" value={password} onChange={(e) => setPassword(e.target.value)} required
              />
            )}
          </Field>
          {loginMutation.isError && (
            <Alert tone="danger">{loginErrorMessage(loginMutation.error)}</Alert>
          )}
          <Button type="submit" variant="primary" isBlock disabled={loginMutation.isPending}>
            {loginMutation.isPending ? '로그인 중...' : '로그인'}
          </Button>
        </form>
        <SignupHint options={options} />
      </div>
    </div>
  )
}
