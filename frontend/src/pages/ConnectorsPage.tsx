import { useState } from 'react'
import { ShieldOff } from 'lucide-react'
import { useConnectors } from '../hooks/useConnectors'
import type { Connector } from '../hooks/useConnectors'
import { useAuthStore } from '../store/authStore'
import ConnectorDetailPanel from '../components/connectors/ConnectorDetailPanel'
import CreateConnectorForm from '../components/connectors/CreateConnectorForm'
import { ACL_MODE_LABELS, STATUS_LABELS, STATUS_TONE, formatDateTime } from '../components/connectors/connectorLabels'
import { Badge, Button, EmptyState, ErrorAlert, Page, PageBody, PageHeader, Spinner, Split, Stat, StatStrip, Toolbar } from '../components/ui'

// v3 마일스톤 3 — 사내 파일 서버(SMB)나 서버 로컬 폴더를 컬렉션에 연결한다(관리자 전용).
// "파일 서버 권한을 따름"으로 가져온 문서의 접근 권한은 원천이 기준이라 문서 화면에서 고칠 수 없다.

function rowClassName(connector: Connector): string | undefined {
  if (connector.last_status === 'failed' || connector.error_count > 0) return 'is-danger'
  if (connector.held_count > 0 || !connector.enabled) return 'is-warning'
  return undefined
}

function ConnectorTable({ connectors, selectedId, onSelect }: {
  connectors: Connector[]; selectedId: string | null; onSelect: (id: string) => void
}) {
  if (connectors.length === 0) {
    return <EmptyState title="아직 연결한 원천이 없습니다." description="새 연결을 추가하면 여기에 나타납니다." />
  }
  return (
    <div className="ds-table-wrap">
      <table className="ds-table ds-table--compact">
        <caption className="sr-only">원천 연결 목록</caption>
        <thead>
          <tr>
            <th scope="col">이름</th>
            <th scope="col">컬렉션</th>
            <th scope="col">권한 기준</th>
            <th scope="col">상태</th>
            <th scope="col" className="ds-cell-num">보류</th>
            <th scope="col" className="ds-cell-num">오류</th>
            <th scope="col">마지막 동기화</th>
          </tr>
        </thead>
        <tbody>
          {connectors.map((c) => {
            const isSelected = c.id === selectedId
            const rowClass = [rowClassName(c), isSelected ? 'is-selected' : ''].filter(Boolean).join(' ') || undefined
            return (
              <tr key={c.id} className={rowClass}>
                <td>
                  <button
                    type="button"
                    className="ds-btn ds-btn--ghost ds-btn--sm"
                    aria-current={isSelected ? 'true' : undefined}
                    onClick={() => onSelect(c.id)}
                  >
                    {c.name}
                  </button>
                  {!c.enabled && <Badge tone="neutral" isPlain>자동 동기화 꺼짐</Badge>}
                </td>
                <td className="ds-cell-muted">{c.collection_name ?? '-'}</td>
                <td>
                  <Badge tone={c.acl_mode === 'collection_only' ? 'warning' : 'info'} isPlain>{ACL_MODE_LABELS[c.acl_mode]}</Badge>
                  {c.kind === 'local' && <span className="ds-cell-sub">로컬 폴더</span>}
                </td>
                <td>
                  {c.last_status
                    ? <Badge tone={STATUS_TONE[c.last_status]} hasDot>{STATUS_LABELS[c.last_status]}</Badge>
                    : <span className="ds-cell-muted">-</span>}
                </td>
                <td className="ds-cell-num">{c.held_count}</td>
                <td className="ds-cell-num">{c.error_count}</td>
                <td className="ds-cell-muted" style={{ whiteSpace: 'nowrap' }}>{formatDateTime(c.last_sync_at)}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export default function ConnectorsPage() {
  const currentUser = useAuthStore((s) => s.user)
  const { data, isLoading, isError, error, refetch } = useConnectors()
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [isCreating, setIsCreating] = useState(false)

  if (currentUser?.role !== 'admin') {
    return (
      <Page>
        <EmptyState icon={<ShieldOff size={48} aria-hidden="true" />} title="관리자만 접근할 수 있습니다." />
      </Page>
    )
  }

  const connectors = data ?? []
  const problemCount = connectors.filter((c) => c.last_status === 'failed' || c.error_count > 0).length
  const heldTotal = connectors.reduce((sum, c) => sum + c.held_count, 0)
  const disabledCount = connectors.filter((c) => !c.enabled).length

  return (
    <Page>
      <PageHeader
        title="문서 원천 연결"
        subtitle="사내 파일 서버나 서버 폴더의 문서를 컬렉션으로 가져옵니다. 권한이나 내용이 바뀌면 다음 동기화 때 반영됩니다."
        actions={(
          <Button variant="secondary" size="sm" aria-expanded={isCreating} onClick={() => setIsCreating((v) => !v)}>
            {isCreating ? '닫기' : '새 연결'}
          </Button>
        )}
      />
      <StatStrip>
        <Stat label="원천 연결" value={connectors.length} />
        <Stat label="오류 연결" value={problemCount} tone={problemCount > 0 ? 'danger' : 'default'} />
        <Stat label="보류 파일" value={heldTotal} tone={heldTotal > 0 ? 'warning' : 'default'} />
        <Stat label="자동 동기화 꺼짐" value={disabledCount} tone={disabledCount > 0 ? 'warning' : 'default'} />
      </StatStrip>

      <Split
        main={(
          <PageBody>
            {isCreating && <CreateConnectorForm onCreated={(id) => { setIsCreating(false); setSelectedId(id) }} />}
            {isLoading && <Spinner />}
            {isError && <ErrorAlert error={error} message="원천 연결 목록을 불러오지 못했습니다." onRetry={() => refetch()} />}
            {!isLoading && !isError && (
              <>
                <Toolbar label="원천 연결 도구" meta={`${connectors.length}개`}>
                  <span className="ds-cell-muted" style={{ fontSize: 'var(--text-sm)' }}>
                    이름을 누르면 오른쪽에 상세가 열립니다.
                  </span>
                </Toolbar>
                <ConnectorTable connectors={connectors} selectedId={selectedId} onSelect={setSelectedId} />
              </>
            )}
          </PageBody>
        )}
        panel={selectedId && !isLoading && !isError ? (
          <ConnectorDetailPanel key={selectedId} connectorId={selectedId} onDeleted={() => setSelectedId(null)} />
        ) : undefined}
      />
    </Page>
  )
}
