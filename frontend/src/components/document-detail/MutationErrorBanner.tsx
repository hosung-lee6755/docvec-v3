import { AlertTriangle, X } from 'lucide-react'
import { errorCause } from '../../lib/apiError'

export interface MutationFailure {
  /** 사용자에게 보이는 작업 이름(예: "태그 저장"). */
  label: string
  /** 실패한 요청의 오류. 원인 문장을 만드는 데 쓴다 */
  error?: unknown
  onDismiss: () => void
}

/**
 * 문서 상세의 저장/삭제/복원 같은 변경 작업이 실패했음을 알린다. 이 화면의 버튼은
 * 낙관적으로 동작하는 것처럼 보이므로, 실패를 알리지 않으면 사용자는 저장된 줄 안다.
 */
export default function MutationErrorBanner({ failures }: { failures: MutationFailure[] }) {
  if (failures.length === 0) return null

  return (
    <div
      role="alert"
      style={{
        marginBottom: 'var(--space-4)', padding: 'var(--space-3) var(--space-4)', background: 'var(--color-danger-bg)',
        border: '1px solid var(--color-danger-border)', borderRadius: 'var(--radius-md)', display: 'flex',
        flexDirection: 'column', gap: 'var(--space-2)',
      }}
    >
      {failures.map((failure) => (
        <div key={failure.label} style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
          <AlertTriangle size={16} style={{ color: 'var(--color-danger)', flexShrink: 0 }} aria-hidden="true" />
          <span style={{ flex: 1, fontSize: 13, color: 'var(--color-danger)' }}>
            {failure.label}에 실패했습니다. {errorCause(failure.error)}
          </span>
          <button
            type="button"
            onClick={failure.onDismiss}
            aria-label={`${failure.label} 오류 닫기`}
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--color-danger)', display: 'inline-flex' }}
          >
            <X size={14} aria-hidden="true" />
          </button>
        </div>
      ))}
    </div>
  )
}
