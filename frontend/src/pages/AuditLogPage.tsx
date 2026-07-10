import { useState } from 'react'
import { ScrollText, Loader2, ShieldOff } from 'lucide-react'
import { useAuditLogs } from '../hooks/useAudit'
import { useAuthStore } from '../store/authStore'

const PAGE_SIZE = 50

const ACTION_LABELS: Record<string, string> = {
  'auth.login': '로그인',
  'auth.login_failed': '로그인 실패',
  'auth.register': '회원가입',
  'document.delete': '문서 삭제',
  'user.update': '사용자 정보 변경',
  'user.delete': '사용자 삭제',
  'api_key.set': 'API 키 등록',
  'api_key.delete': 'API 키 삭제',
  'project.member_invite': '프로젝트 멤버 초대',
  'project.member_remove': '프로젝트 멤버 제거',
}

export default function AuditLogPage() {
  const currentUser = useAuthStore((s) => s.user)
  const [action, setAction] = useState('')
  const [page, setPage] = useState(0)

  const { data, isLoading, isError } = useAuditLogs({
    action: action || undefined,
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
  })

  if (currentUser?.role !== 'admin') {
    return (
      <div style={{ textAlign: 'center', padding: 'var(--space-8)', color: 'var(--color-text-muted)' }}>
        <ShieldOff size={48} style={{ margin: '0 auto var(--space-4)', display: 'block', opacity: 0.4 }} />
        <p>관리자만 접근할 수 있습니다.</p>
      </div>
    )
  }

  const totalPages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1

  return (
    <div>
      <style>{'@keyframes spin { to { transform: rotate(360deg) } }'}</style>

      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', marginBottom: 'var(--space-6)' }}>
        <h1 style={{ fontSize: 24, fontWeight: 700 }}>감사 로그</h1>
      </div>

      <div style={{ marginBottom: 'var(--space-4)', display: 'flex', gap: 'var(--space-3)', alignItems: 'center' }}>
        <select
          value={action}
          onChange={(e) => {
            setAction(e.target.value)
            setPage(0)
          }}
          className="krds-form-select small"
        >
          <option value="">전체 액션</option>
          {Object.entries(ACTION_LABELS).map(([key, label]) => (
            <option key={key} value={key}>{label}</option>
          ))}
        </select>
      </div>

      {isLoading && (
        <div style={{ display: 'flex', justifyContent: 'center', padding: 'var(--space-8)' }}>
          <Loader2 size={24} style={{ animation: 'spin 1s linear infinite', color: 'var(--color-text-muted)' }} />
        </div>
      )}

      {isError && (
        <div style={{
          background: '#fef2f2', border: '1px solid #fecaca',
          borderRadius: 'var(--radius-md)', padding: 'var(--space-4)',
          color: '#dc2626', marginBottom: 'var(--space-4)',
        }}>
          감사 로그를 불러오지 못했습니다.
        </div>
      )}

      {!isLoading && !isError && (data?.items.length ?? 0) === 0 && (
        <div style={{ textAlign: 'center', padding: 'var(--space-8)', color: 'var(--color-text-muted)' }}>
          <ScrollText size={48} style={{ margin: '0 auto var(--space-4)', display: 'block', opacity: 0.4 }} />
          <p>기록된 로그가 없습니다.</p>
        </div>
      )}

      {!isLoading && !isError && (data?.items.length ?? 0) > 0 && (
        <>
          <div className="krds-table-wrap">
            <table className="tbl col data">
              <caption>감사 로그 목록</caption>
              <colgroup>
                <col style={{ width: '18%' }} />
                <col style={{ width: '15%' }} />
                <col style={{ width: '12%' }} />
                <col style={{ width: '15%' }} />
                <col style={{ width: '12%' }} />
                <col />
              </colgroup>
              <thead>
                <tr>
                  <th scope="col">시각</th>
                  <th scope="col">액션</th>
                  <th scope="col">리소스 유형</th>
                  <th scope="col">리소스 ID</th>
                  <th scope="col">IP</th>
                  <th scope="col">상세</th>
                </tr>
              </thead>
              <tbody>
                {data?.items.map((row) => (
                  <tr key={row.id}>
                    <td style={{ whiteSpace: 'nowrap', color: 'var(--color-text-muted)' }}>
                      {new Date(row.created_at).toLocaleString('ko-KR')}
                    </td>
                    <td style={{ fontWeight: 500 }}>{ACTION_LABELS[row.action] ?? row.action}</td>
                    <td>{row.resource_type ?? '-'}</td>
                    <td style={{ fontFamily: 'monospace', fontSize: 12 }}>{row.resource_id ?? '-'}</td>
                    <td style={{ color: 'var(--color-text-muted)' }}>{row.ip_address ?? '-'}</td>
                    <td style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
                      {row.detail ? JSON.stringify(row.detail) : '-'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div style={{ display: 'flex', justifyContent: 'center', gap: 'var(--space-3)', marginTop: 'var(--space-4)' }}>
            <button
              className="krds-btn small secondary"
              disabled={page === 0}
              onClick={() => setPage((p) => Math.max(0, p - 1))}
            >이전</button>
            <span style={{ color: 'var(--color-text-muted)', alignSelf: 'center' }}>
              {page + 1} / {totalPages}
            </span>
            <button
              className="krds-btn small secondary"
              disabled={page + 1 >= totalPages}
              onClick={() => setPage((p) => p + 1)}
            >다음</button>
          </div>
        </>
      )}
    </div>
  )
}
