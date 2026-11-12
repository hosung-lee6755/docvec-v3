import { useState } from 'react'
import { ScrollText, ShieldOff } from 'lucide-react'
import { useAuditLogs } from '../hooks/useAudit'
import type { AuditLogItem } from '../hooks/useAudit'
import { useAuthStore } from '../store/authStore'
import {
  Alert, Button, EmptyState, Page, PageBody, PageHeader, Select, Spinner, Stat, StatStrip, Toolbar,
} from '../components/ui'

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
  'group.create': '그룹 생성',
  'group.update': '그룹 수정',
  'group.delete': '그룹 삭제',
  'group.member_add': '그룹 멤버 추가',
  'group.member_remove': '그룹 멤버 제거',
  'user.clearance_update': '열람등급 변경',
  'document.security_level_update': '문서 보안등급 변경',
  'document.acl_update': '문서 접근 허용 변경',
  'collection.security_level_update': '컬렉션 기본 등급 변경',
  'document.preview': '원문 미리보기',
  'document.download': '원문 다운로드',
  'collection.export': '컬렉션 내보내기',
  'answer_trace.view': '답변 추적 열람',
  'governance.report_download': 'AI 기본법 근거 자료 내려받기',
  'connector.create': '원천 연결 추가',
  'connector.update': '원천 연결 수정',
  'connector.delete': '원천 연결 삭제',
  'connector.sync_request': '원천 동기화 요청',
  'connector.sync': '원천 동기화 실행',
  'directory.sync': 'AD 동기화',
  'directory.sync_failed': 'AD 동기화 실패',
  'access_token.create': '외부 에이전트 토큰 발급',
  'access_token.revoke': '외부 에이전트 토큰 회수',
  'mcp.tool_call': '외부 에이전트 도구 호출',
}

// 원문이나 추적 기록을 열어 본 행. 누가 무엇을 봤는지 확인해야 하므로 주의 색을 쓴다.
const EXPOSURE_ACTIONS = new Set([
  'document.preview', 'document.download', 'collection.export', 'answer_trace.view', 'governance.report_download',
])

function rowClassName(row: AuditLogItem): string | undefined {
  if (row.action === 'auth.login_failed') return 'is-danger'
  if (EXPOSURE_ACTIONS.has(row.action)) return 'is-warning'
  return undefined
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
      <Page>
        <EmptyState icon={<ShieldOff size={48} aria-hidden="true" />} title="관리자만 접근할 수 있습니다." />
      </Page>
    )
  }

  const items = data?.items ?? []
  const total = data?.total ?? 0
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const loginFailedCount = items.filter((row) => row.action === 'auth.login_failed').length
  const exposureCount = items.filter((row) => EXPOSURE_ACTIONS.has(row.action)).length

  return (
    <Page>
      <PageHeader title="감사 로그" subtitle="관리자와 사용자의 주요 작업 기록입니다. 요약 칸은 이 페이지에 보이는 행만 셉니다." />
      <StatStrip>
        <Stat label="전체 기록" value={total.toLocaleString('ko-KR')} />
        <Stat label="이 페이지 로그인 실패" value={loginFailedCount} tone={loginFailedCount > 0 ? 'danger' : 'default'} />
        <Stat label="이 페이지 원문·추적 열람" value={exposureCount} tone={exposureCount > 0 ? 'warning' : 'default'} />
      </StatStrip>

      <Toolbar label="감사 로그 거르기" meta={`${page + 1} / ${totalPages} 쪽`}>
        <Select
          controlSize="sm"
          aria-label="액션 거르기"
          value={action}
          onChange={(e) => {
            setAction(e.target.value)
            setPage(0)
          }}
          style={{ minWidth: 200 }}
        >
          <option value="">전체 액션</option>
          {Object.entries(ACTION_LABELS).map(([key, label]) => (
            <option key={key} value={key}>{label}</option>
          ))}
        </Select>
      </Toolbar>

      <PageBody>
        {isLoading && <Spinner />}
        {isError && <Alert tone="danger">감사 로그를 불러오지 못했습니다.</Alert>}
        {!isLoading && !isError && items.length === 0 && (
          <EmptyState icon={<ScrollText size={48} aria-hidden="true" />} title="기록된 로그가 없습니다." />
        )}

        {!isLoading && !isError && items.length > 0 && (
          <>
            <div className="ds-table-wrap">
              <table className="ds-table ds-table--compact">
                <caption className="sr-only">감사 로그 목록</caption>
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
                  {items.map((row) => (
                    <tr key={row.id} className={rowClassName(row)}>
                      <td className="ds-cell-muted" style={{ whiteSpace: 'nowrap' }}>
                        {new Date(row.created_at).toLocaleString('ko-KR')}
                      </td>
                      <td style={{ fontWeight: 500 }}>{ACTION_LABELS[row.action] ?? row.action}</td>
                      <td>{row.resource_type ?? '-'}</td>
                      <td style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-xs)' }}>{row.resource_id ?? '-'}</td>
                      <td className="ds-cell-muted">{row.ip_address ?? '-'}</td>
                      <td className="ds-cell-muted" style={{ fontSize: 'var(--text-xs)', maxWidth: 320, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                        title={row.detail ? JSON.stringify(row.detail) : undefined}>
                        {row.detail ? JSON.stringify(row.detail) : '-'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 'var(--space-3)' }}>
              <Button variant="secondary" size="sm" disabled={page === 0} onClick={() => setPage((p) => Math.max(0, p - 1))}>이전</Button>
              <span className="ds-cell-muted" style={{ fontSize: 'var(--text-sm)' }}>{page + 1} / {totalPages}</span>
              <Button variant="secondary" size="sm" disabled={page + 1 >= totalPages} onClick={() => setPage((p) => p + 1)}>다음</Button>
            </div>
          </>
        )}
      </PageBody>
    </Page>
  )
}
