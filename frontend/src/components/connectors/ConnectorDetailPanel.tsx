import { useState } from 'react'
import { PlugZap, RefreshCw, Trash2 } from 'lucide-react'
import {
  useConnector, useDeleteConnector, useSyncConnector, useTestConnector, useUpdateConnector,
} from '../../hooks/useConnectors'
import type { ConnectorDetail, LevelRule } from '../../hooks/useConnectors'
import LevelRulesEditor from './LevelRulesEditor'
import {
  COUNT_LABELS, STATUS_LABELS, STATUS_TONE, cleanRules, errorMessage, formatDateTime, reasonLabel,
} from './connectorLabels'
import { Alert, Badge, Button, Field, Input, SidePanel, Spinner } from '../ui'

// 원천 연결 하나의 상세: 설정 수정, 지금 동기화, 연결 확인, 최근 실행, 보류·오류 파일.

const MIN_INTERVAL = 5
const SYNC_WAIT_MS = 60_000

interface Draft {
  name: string
  password: string
  sync_interval_minutes: number
  enabled: boolean
  level_rules: LevelRule[]
}

function toDraft(c: ConnectorDetail): Draft {
  return {
    name: c.name, password: '', sync_interval_minutes: c.sync_interval_minutes,
    enabled: c.enabled, level_rules: c.level_rules,
  }
}

function uncPath(c: ConnectorDetail): string {
  const base = c.base_path ? `\\${c.base_path.replace(/\//g, '\\')}` : ''
  return `\\\\${c.host}\\${c.share}${base}`
}

function SettingsForm({ connector }: { connector: ConnectorDetail }) {
  const update = useUpdateConnector()
  const [draft, setDraft] = useState<Draft>(() => toDraft(connector))
  const isIntervalValid = Number.isInteger(draft.sync_interval_minutes) && draft.sync_interval_minutes >= MIN_INTERVAL

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    update.mutate(
      {
        id: connector.id,
        input: {
          name: draft.name.trim(),
          sync_interval_minutes: draft.sync_interval_minutes,
          enabled: draft.enabled,
          level_rules: cleanRules(draft.level_rules),
          // 비워 두면 기존 비밀번호를 그대로 쓴다
          ...(draft.password ? { password: draft.password } : {}),
        },
      },
      { onSuccess: () => setDraft((d) => ({ ...d, password: '' })) },
    )
  }

  return (
    <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
      <Field label="이름">
        {(id) => (
          <Input id={id} value={draft.name} maxLength={255} required controlSize="sm"
            onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
        )}
      </Field>
      <Field label="새 비밀번호" hint="바꿀 때만 입력합니다">
        {(id) => (
          <Input id={id} type="password" autoComplete="new-password" value={draft.password} placeholder="바꿀 때만 입력"
            controlSize="sm" onChange={(e) => setDraft({ ...draft, password: e.target.value })} />
        )}
      </Field>
      <Field label="동기화 주기(분)">
        {(id) => (
          <Input id={id} type="number" min={5} max={10080} value={draft.sync_interval_minutes} controlSize="sm"
            onChange={(e) => setDraft({ ...draft, sync_interval_minutes: Number(e.target.value) })} />
        )}
      </Field>
      <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 'var(--text-sm)' }}>
        <input type="checkbox" checked={draft.enabled} onChange={(e) => setDraft({ ...draft, enabled: e.target.checked })} />
        자동 동기화 사용
      </label>
      <LevelRulesEditor rules={draft.level_rules} onChange={(level_rules) => setDraft({ ...draft, level_rules })} disabled={update.isPending} />
      <div style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'center', flexWrap: 'wrap' }}>
        <Button type="submit" variant="primary" size="sm" disabled={update.isPending || !draft.name.trim() || !isIntervalValid}>
          설정 저장
        </Button>
        {update.isSuccess && <span role="status" className="ds-cell-muted" style={{ fontSize: 'var(--text-xs)' }}>저장했습니다. 등급 규칙은 다음 동기화부터 적용됩니다.</span>}
        {update.isError && <span role="alert" style={{ fontSize: 'var(--text-xs)', color: 'var(--color-danger)' }}>{errorMessage(update.error, '설정을 저장하지 못했습니다.')}</span>}
      </div>
    </form>
  )
}

function runSummary(counts: Record<string, number>): string {
  const parts = Object.entries(counts).filter(([, n]) => n > 0).map(([k, n]) => `${COUNT_LABELS[k] ?? k} ${n}`)
  return parts.length > 0 ? parts.join(', ') : '-'
}

function RunHistory({ connector }: { connector: ConnectorDetail }) {
  if (connector.runs.length === 0) return <p className="ds-cell-muted" style={{ margin: 0, fontSize: 'var(--text-sm)' }}>아직 동기화한 적이 없습니다.</p>
  return (
    <div className="ds-table-wrap">
      <table className="ds-table ds-table--compact" style={{ fontSize: 'var(--text-sm)' }}>
        <caption className="sr-only">최근 실행 기록</caption>
        <thead><tr><th scope="col">시작</th><th scope="col">상태</th><th scope="col">결과</th></tr></thead>
        <tbody>
          {connector.runs.map((run) => (
            <tr key={run.id}>
              <td className="ds-cell-muted" style={{ whiteSpace: 'nowrap' }}>{formatDateTime(run.started_at)}</td>
              <td><Badge tone={STATUS_TONE[run.status]} hasDot>{STATUS_LABELS[run.status]}</Badge></td>
              <td>
                {runSummary(run.counts)}
                {run.error_message && <span className="ds-cell-sub" style={{ color: 'var(--color-danger)' }}>{run.error_message}</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function ProblemItems({ connector }: { connector: ConnectorDetail }) {
  if (connector.problem_items.length === 0) return <p className="ds-cell-muted" style={{ margin: 0, fontSize: 'var(--text-sm)' }}>보류되거나 실패한 파일이 없습니다.</p>
  return (
    <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
      {connector.problem_items.map((item) => (
        <li key={item.path} style={{ fontSize: 'var(--text-sm)' }}>
          <Badge tone={item.state === 'held' ? 'warning' : 'danger'} hasDot>
            {item.state === 'held' ? '보류' : '오류'}
          </Badge>
          <code style={{ marginLeft: 6, wordBreak: 'break-all' }}>{item.path}</code>
          <span className="ds-cell-sub">{reasonLabel(item.reason)}</span>
        </li>
      ))}
    </ul>
  )
}

function TestResult({ ok, error, sample }: { ok: boolean; error: string | null; sample: string[] }) {
  if (!ok) return <Alert tone="danger">연결하지 못했습니다({error}). 주소, 계정, 하위 경로를 확인하세요.</Alert>
  const found = sample.length > 0 ? `읽은 파일 예: ${sample.join(', ')}` : '읽을 수 있는 파일이 아직 없습니다.'
  return <Alert tone="success">연결됐습니다. {found}</Alert>
}

function Actions({ connector, onDeleted, onSyncRequested }: {
  connector: ConnectorDetail; onDeleted: () => void; onSyncRequested: () => void
}) {
  const sync = useSyncConnector()
  const test = useTestConnector()
  const remove = useDeleteConnector()
  const [isConfirming, setIsConfirming] = useState(false)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
      <div style={{ display: 'flex', gap: 'var(--space-2)', flexWrap: 'wrap' }}>
        <Button variant="primary" size="sm" disabled={sync.isPending} onClick={() => sync.mutate(connector.id, { onSuccess: onSyncRequested })}
          icon={<RefreshCw size={14} aria-hidden="true" />}>
          지금 동기화
        </Button>
        <Button variant="secondary" size="sm" disabled={test.isPending} onClick={() => test.mutate(connector.id)}
          icon={<PlugZap size={14} aria-hidden="true" />}>
          연결 확인
        </Button>
        {!isConfirming ? (
          <Button variant="danger" size="sm" onClick={() => setIsConfirming(true)} icon={<Trash2 size={14} aria-hidden="true" />}>
            삭제
          </Button>
        ) : null}
      </div>
      {isConfirming && (
        <Alert tone="danger">
          <span>이 연결로 가져온 문서도 모두 지워집니다.</span>
          <span style={{ display: 'flex', gap: 'var(--space-2)', marginTop: 'var(--space-2)' }}>
            <Button variant="danger-solid" size="sm" disabled={remove.isPending}
              onClick={() => remove.mutate(connector.id, { onSuccess: onDeleted })}>삭제 확인</Button>
            <Button variant="ghost" size="sm" onClick={() => setIsConfirming(false)}>취소</Button>
          </span>
        </Alert>
      )}
      {sync.isSuccess && <span role="status" className="ds-cell-muted" style={{ fontSize: 'var(--text-xs)' }}>동기화를 요청했습니다. 결과는 아래 실행 기록에 나타납니다.</span>}
      {sync.isError && <span role="alert" style={{ fontSize: 'var(--text-xs)', color: 'var(--color-danger)' }}>{errorMessage(sync.error, '동기화를 요청하지 못했습니다.')}</span>}
      {test.data && <TestResult ok={test.data.ok} error={test.data.error} sample={test.data.sample} />}
      {test.isError && <span role="alert" style={{ fontSize: 'var(--text-xs)', color: 'var(--color-danger)' }}>{errorMessage(test.error, '연결 확인을 요청하지 못했습니다.')}</span>}
      {remove.isError && <span role="alert" style={{ fontSize: 'var(--text-xs)', color: 'var(--color-danger)' }}>{errorMessage(remove.error, '연결을 삭제하지 못했습니다.')}</span>}
    </div>
  )
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <h3 className="ds-section-title" style={{ fontSize: 'var(--text-sm)', color: 'var(--color-text)', fontWeight: 'var(--weight-semibold)' }}>{children}</h3>
}

export default function ConnectorDetailPanel({ connectorId, onDeleted }: { connectorId: string; onDeleted: () => void }) {
  const [pollUntil, setPollUntil] = useState(0)
  const { data: connector, isLoading, isError } = useConnector(connectorId, pollUntil)

  if (isLoading) {
    return (
      <SidePanel title="원천 연결 상세" label="원천 연결 상세">
        <Spinner />
      </SidePanel>
    )
  }
  if (isError || !connector) {
    return (
      <SidePanel title="원천 연결 상세" label="원천 연결 상세">
        <Alert tone="danger">연결 정보를 불러오지 못했습니다.</Alert>
      </SidePanel>
    )
  }

  return (
    <SidePanel
      eyebrow={connector.enabled ? '원천 연결' : '원천 연결 · 자동 동기화 꺼짐'}
      title={connector.name}
      label="원천 연결 상세"
    >
      <p className="ds-cell-muted" style={{ margin: 0, fontSize: 'var(--text-xs)', lineHeight: 1.6, wordBreak: 'break-all' }}>
        <code>{uncPath(connector)}</code>
        <br />
        계정 {connector.username} · 컬렉션 {connector.collection_name ?? '-'} · 마지막 동기화 {formatDateTime(connector.last_sync_at)}
      </p>
      <Actions connector={connector} onDeleted={onDeleted} onSyncRequested={() => setPollUntil(Date.now() + SYNC_WAIT_MS)} />
      <SettingsForm key={connector.id} connector={connector} />
      <SectionTitle>보류·오류 파일 ({connector.held_count + connector.error_count})</SectionTitle>
      <p className="ds-cell-muted" style={{ margin: 0, fontSize: 'var(--text-xs)' }}>
        권한을 그대로 옮길 수 없는 파일은 넓게 열지 않고 보류합니다. 파일 서버에서 권한을 고치면 다음 동기화 때 다시 판단합니다.
      </p>
      <ProblemItems connector={connector} />
      <SectionTitle>최근 실행</SectionTitle>
      <RunHistory connector={connector} />
    </SidePanel>
  )
}
