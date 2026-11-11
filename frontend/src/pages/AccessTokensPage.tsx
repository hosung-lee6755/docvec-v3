import { Loader2, ShieldOff } from 'lucide-react'
import {
  TOKEN_STATUS_BADGE, TOKEN_STATUS_LABELS, useAllAccessTokens, useRevokeAnyAccessToken,
} from '../hooks/useAccessTokens'
import { useAuthStore } from '../store/authStore'
import { errorMessage, formatDateTime } from '../components/connectors/connectorLabels'

// v3 마일스톤 4 — 관리자가 전 직원의 외부 에이전트 토큰을 보고 회수한다.
// 퇴사자나 유출이 의심되는 토큰을 바로 끊을 수 있어야 한다. 토큰 원문은 관리자도 볼 수 없다.

const MUTED: React.CSSProperties = { color: 'var(--color-text-muted)' }

export default function AccessTokensPage() {
  const currentUser = useAuthStore((s) => s.user)
  const isAdmin = currentUser?.role === 'admin'
  const { data, isLoading, isError } = useAllAccessTokens(isAdmin)
  const revoke = useRevokeAnyAccessToken()

  if (!isAdmin) {
    return (
      <div style={{ textAlign: 'center', padding: 'var(--space-8)', ...MUTED }}>
        <ShieldOff size={48} style={{ margin: '0 auto var(--space-4)', display: 'block', opacity: 0.4 }} />
        <p>관리자만 접근할 수 있습니다.</p>
      </div>
    )
  }

  const handleRevoke = (id: string, label: string) => {
    if (!window.confirm(`${label} 토큰을 회수할까요? 이 토큰을 쓰는 에이전트는 바로 연결이 끊깁니다.`)) return
    revoke.mutate(id)
  }

  return (
    <div>
      <style>{'@keyframes spin { to { transform: rotate(360deg) } }'}</style>
      <h1 style={{ fontSize: 24, fontWeight: 700 }}>외부 에이전트 토큰</h1>
      <p style={{ fontSize: 13, marginTop: 4, marginBottom: 'var(--space-5)', ...MUTED }}>
        직원이 AI 에이전트에 넣은 개인 접근 토큰입니다. 에이전트는 토큰 주인과 같은 권한으로만 움직이며,
        도구 호출 기록은 감사 로그의 &lsquo;외부 에이전트 도구 호출&rsquo;에서 볼 수 있습니다.
        {data && !data.mcp_enabled && ' 지금은 외부 에이전트 연결이 꺼져 있어 어떤 토큰도 쓸 수 없습니다.'}
      </p>

      {isLoading && <Loader2 size={24} style={{ animation: 'spin 1s linear infinite' }} />}
      {isError && <p style={{ color: '#dc2626', fontSize: 13 }}>토큰 목록을 불러오지 못했습니다.</p>}
      {revoke.isError && <p style={{ color: '#dc2626', fontSize: 13 }}>{errorMessage(revoke.error, '토큰을 회수하지 못했습니다.')}</p>}

      {data && data.items.length === 0 && <p style={{ fontSize: 13, ...MUTED }}>발급된 토큰이 없습니다.</p>}
      {data && data.items.length > 0 && (
        <table className="krds-table" style={{ width: '100%', fontSize: 13 }}>
          <thead>
            <tr>
              <th scope="col">직원</th>
              <th scope="col">토큰 이름</th>
              <th scope="col">상태</th>
              <th scope="col">발급</th>
              <th scope="col">만료</th>
              <th scope="col">마지막 사용</th>
              <th scope="col"><span className="sr-only">작업</span></th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((t) => (
              <tr key={t.id}>
                <td>{t.username}<span style={{ display: 'block', fontSize: 12, ...MUTED }}>{t.email}</span></td>
                <td>{t.name}<span style={{ display: 'block', fontSize: 12, ...MUTED }}>{t.token_prefix}…</span></td>
                <td><span className={`krds-badge xsmall ${TOKEN_STATUS_BADGE[t.status]}`}>{TOKEN_STATUS_LABELS[t.status]}</span></td>
                <td style={MUTED}>{formatDateTime(t.created_at)}</td>
                <td style={MUTED}>{formatDateTime(t.expires_at)}</td>
                <td style={MUTED}>{formatDateTime(t.last_used_at)}</td>
                <td>
                  {t.status === 'active' && (
                    <button type="button" className="krds-btn xsmall text" style={{ color: '#dc2626' }}
                      disabled={revoke.isPending} onClick={() => handleRevoke(t.id, `${t.username}의 "${t.name}"`)}
                      aria-label={`${t.username}의 ${t.name} 회수`}>
                      회수
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
