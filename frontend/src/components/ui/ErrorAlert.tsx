import { RefreshCw } from 'lucide-react'
import { errorCause } from '../../lib/apiError'
import { Button } from './Button'
import { Alert } from './Page'

interface ErrorAlertProps {
  /** 실패한 요청의 오류(react-query의 error 등) */
  error: unknown
  /** 무엇을 못 했는지. 예: "그룹 목록을 불러오지 못했습니다." */
  message: string
  /** 다시 불러오기가 의미 있는 경우(목록 조회 등)에만 넘긴다 */
  onRetry?: () => void
}

/** 실패 알림. 첫 줄은 무엇을 못 했는지, 둘째 줄은 원인과 할 일을 보인다. */
export function ErrorAlert({ error, message, onRetry }: ErrorAlertProps) {
  return (
    <Alert tone="danger">
      <span className="ds-alert__title">{message}</span>
      <span className="ds-alert__cause">{errorCause(error)}</span>
      {onRetry && (
        <span className="ds-alert__actions">
          <Button size="sm" variant="secondary" icon={<RefreshCw size={14} aria-hidden="true" />} onClick={onRetry}>
            다시 시도
          </Button>
        </span>
      )}
    </Alert>
  )
}

interface ErrorTextProps {
  error: unknown
  message: string
}

/** 표 칸, 패널 줄처럼 상자를 넣기 좁은 자리의 한 줄 실패 문구 */
export function ErrorText({ error, message }: ErrorTextProps) {
  return (
    <span role="alert" className="ds-error-text">
      {message} {errorCause(error)}
    </span>
  )
}
