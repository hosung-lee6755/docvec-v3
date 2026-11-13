import { ShieldOff } from 'lucide-react'
import {
  TOKEN_STATUS_BADGE, TOKEN_STATUS_LABELS, useAllAccessTokens, useRevokeAnyAccessToken,
} from '../hooks/useAccessTokens'
import { useAuthStore } from '../store/authStore'
import { formatDateTime } from '../components/connectors/connectorLabels'
import { Alert, Badge, Button, EmptyState, ErrorAlert, Page, PageBody, PageHeader, Stat, StatStrip, toneFromKrdsClass } from '../components/ui'
import '../styles/screens/user.css'

// v3 마일스톤 4 — 관리자가 전 직원의 외부 에이전트 토큰을 보고 회수한다.
// 퇴사자나 유출이 의심되는 토큰을 바로 끊을 수 있어야 한다. 토큰 원문은 관리자도 볼 수 없다.

export default function AccessTokensPage() {
  const currentUser = useAuthStore((s) => s.user)
  const isAdmin = currentUser?.role === 'admin'
  const { data, isLoading, isError, error, refetch } = useAllAccessTokens(isAdmin)
  const revoke = useRevokeAnyAccessToken()

  if (!isAdmin) {
    return (
      <Page>
        <PageBody>
          <EmptyState icon={<ShieldOff size={48} aria-hidden="true" />} title="관리자만 접근할 수 있습니다." />
        </PageBody>
      </Page>
    )
  }

  const handleRevoke = (id: string, label: string) => {
    if (!window.confirm(`${label} 토큰을 회수할까요? 이 토큰을 쓰는 에이전트는 바로 연결이 끊깁니다.`)) return
    revoke.mutate(id)
  }

  // 요약 띠는 이 화면이 이미 받아 온 목록으로만 계산한다(새 API 호출 없음).
  const items = data?.items ?? []
  const countOf = (status: string) => items.filter((t) => t.status === status).length

  return (
    <Page>
      <PageHeader
        title="외부 에이전트 토큰"
        subtitle="직원이 AI 에이전트에 넣은 개인 접근 토큰입니다. 에이전트는 토큰 주인과 같은 권한으로만 움직이며, 도구 호출 기록은 감사 로그의 ‘외부 에이전트 도구 호출’에서 볼 수 있습니다."
      />
      <StatStrip label="토큰 요약">
        <Stat label="전체 토큰" value={items.length} />
        <Stat label="활성 토큰" value={countOf('active')} tone="success" />
        <Stat label="만료 토큰" value={countOf('expired')} tone={countOf('expired') > 0 ? 'warning' : 'default'} />
        <Stat label="회수된 토큰" value={countOf('revoked')} />
      </StatStrip>

      <PageBody>
        {data && !data.mcp_enabled && (
          <Alert tone="warning">지금은 외부 에이전트 연결이 꺼져 있어 어떤 토큰도 쓸 수 없습니다.</Alert>
        )}

        {isLoading && <div className="user-spinner" role="status"><span className="sr-only">로딩 중</span></div>}
        {isError && <ErrorAlert error={error} message="토큰 목록을 불러오지 못했습니다." onRetry={() => refetch()} />}
        {revoke.isError && <ErrorAlert error={revoke.error} message="토큰을 회수하지 못했습니다." />}

        {data && items.length === 0 && <EmptyState title="발급된 토큰이 없습니다." />}
        {data && items.length > 0 && (
          <div className="ds-table-wrap">
            <table className="ds-table">
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
                {items.map((t) => (
                  <tr key={t.id} className={t.status === 'expired' ? 'is-warning' : undefined}>
                    <td>
                      {t.username}
                      <span className="ds-cell-sub">{t.email}</span>
                    </td>
                    <td>
                      {t.name}
                      <span className="ds-cell-sub">{t.token_prefix}…</span>
                    </td>
                    <td>
                      <Badge tone={toneFromKrdsClass(TOKEN_STATUS_BADGE[t.status])} hasDot>
                        {TOKEN_STATUS_LABELS[t.status]}
                      </Badge>
                    </td>
                    <td className="user-token__muted">{formatDateTime(t.created_at)}</td>
                    <td className="user-token__muted">{formatDateTime(t.expires_at)}</td>
                    <td className="user-token__muted">{formatDateTime(t.last_used_at)}</td>
                    <td>
                      {t.status === 'active' && (
                        <Button
                          variant="danger"
                          size="sm"
                          disabled={revoke.isPending}
                          onClick={() => handleRevoke(t.id, `${t.username}의 "${t.name}"`)}
                          aria-label={`${t.username}의 ${t.name} 회수`}
                        >
                          회수
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </PageBody>
    </Page>
  )
}
