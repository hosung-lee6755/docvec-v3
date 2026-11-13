import { CopyButton } from '../settings/AccessTokenGuide'
import { Alert } from '../ui'

interface TemporaryPasswordProps {
  email: string
  password: string
}

/** 임시 비밀번호는 서버에 남지 않으므로 이 자리에서 한 번만 보여 준다 */
export default function TemporaryPassword({ email, password }: TemporaryPasswordProps) {
  return (
    <div className="user-account-secret">
      <Alert tone="warning">
        이 임시 비밀번호는 지금 한 번만 보입니다. 창을 닫기 전에 {email} 사용자에게 전달하세요.
        사용자는 처음 로그인할 때 새 비밀번호를 정해야 합니다.
      </Alert>
      <div className="user-account-secret__row">
        <code className="user-account-secret__value" aria-label={`${email} 임시 비밀번호`}>{password}</code>
        <CopyButton text={password} label="임시 비밀번호 복사" />
      </div>
    </div>
  )
}
