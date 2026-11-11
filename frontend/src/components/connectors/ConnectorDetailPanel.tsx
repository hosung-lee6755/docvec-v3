import { useState } from 'react'
import { Loader2, PlugZap, RefreshCw, Trash2 } from 'lucide-react'
import {
  useConnector, useDeleteConnector, useSyncConnector, useTestConnector, useUpdateConnector,
} from '../../hooks/useConnectors'
import type { ConnectorDetail, LevelRule } from '../../hooks/useConnectors'
import LevelRulesEditor from './LevelRulesEditor'
import {
  COUNT_LABELS, STATUS_BADGE, STATUS_LABELS, cleanRules, errorMessage, formatDateTime, reasonLabel,
} from './connectorLabels'

// 원천 연결 하나의 상세: 설정 수정, 지금 동기화, 연결 확인, 최근 실행, 보류·오류 파일.

const ERROR_TEXT: React.CSSProperties = { fontSize: 12, color: '#dc2626' }
const MUTED: React.CSSProperties = { fontSize: 12, color: 'var(--color-text-muted)' }
const INPUT: React.CSSProperties = { fontSize: 13, padding: '4px 8px', border: '1px solid #e2e8f0', borderRadius: 4 }
const FIELD: React.CSSProperties = { display: 'flex', flexDirection: 'column', gap: 4, fontSize: 13 }
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
    <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)', marginBottom: 'var(--space-5)' }}>
      <span style={{ display: 'flex', gap: 'var(--space-3)', flexWrap: 'wrap' }}>
        <label style={FIELD}>
          이름
          <input style={INPUT} value={draft.name} maxLength={255} required
            onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
        </label>
        <label style={FIELD}>
          새 비밀번호
          <input style={INPUT} type="password" autoComplete="new-password" value={draft.password} placeholder="바꿀 때만 입력"
            onChange={(e) => setDraft({ ...draft, password: e.target.value })} />
        </label>
        <label style={FIELD}>
          동기화 주기(분)
          <input style={{ ...INPUT, width: 100 }} type="number" min={5} max={10080} value={draft.sync_interval_minutes}
            onChange={(e) => setDraft({ ...draft, sync_interval_minutes: Number(e.target.value) })} />
        </label>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, alignSelf: 'flex-end' }}>
          <input type="checkbox" checked={draft.enabled} onChange={(e) => setDraft({ ...draft, enabled: e.target.checked })} />
          자동 동기화 사용
        </label>
      </span>
      <LevelRulesEditor rules={draft.level_rules} onChange={(level_rules) => setDraft({ ...draft, level_rules })} disabled={update.isPending} />
      <span style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'center' }}>
        <button type="submit" className="krds-btn xsmall primary" disabled={update.isPending || !draft.name.trim() || !isIntervalValid}>설정 저장</button>
        {update.isSuccess && <span role="status" style={MUTED}>저장했습니다. 등급 규칙은 다음 동기화부터 적용됩니다.</span>}
        {update.isError && <span role="alert" style={ERROR_TEXT}>{errorMessage(update.error, '설정을 저장하지 못했습니다.')}</span>}
      </span>
    </form>
  )
}

function runSummary(counts: Record<string, number>): string {
  const parts = Object.entries(counts).filter(([, n]) => n > 0).map(([k, n]) => `${COUNT_LABELS[k] ?? k} ${n}`)
  return parts.length > 0 ? parts.join(', ') : '-'
}

function RunHistory({ connector }: { connector: ConnectorDetail }) {
  if (connector.runs.length === 0) return <p style={MUTED}>아직 동기화한 적이 없습니다.</p>
  return (
    <table className="krds-table" style={{ width: '100%', fontSize: 12 }}>
      <thead><tr><th>시작</th><th>상태</th><th>결과</th></tr></thead>
      <tbody>
        {connector.runs.map((run) => (
          <tr key={run.id}>
            <td>{formatDateTime(run.started_at)}</td>
            <td><span className={`krds-badge xsmall ${STATUS_BADGE[run.status]}`}>{STATUS_LABELS[run.status]}</span></td>
            <td>
              {runSummary(run.counts)}
              {run.error_message && <span style={{ ...ERROR_TEXT, display: 'block' }}>{run.error_message}</span>}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function ProblemItems({ connector }: { connector: ConnectorDetail }) {
  if (connector.problem_items.length === 0) return <p style={MUTED}>보류되거나 실패한 파일이 없습니다.</p>
  return (
    <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: 6 }}>
      {connector.problem_items.map((item) => (
        <li key={item.path} style={{ fontSize: 12 }}>
          <span className={`krds-badge xsmall ${item.state === 'held' ? 'bg-warning' : 'bg-danger'}`} style={{ marginRight: 6 }}>
            {item.state === 'held' ? '보류' : '오류'}
          </span>
          <code>{item.path}</code>
          <span style={{ ...MUTED, display: 'block', marginLeft: 4 }}>{reasonLabel(item.reason)}</span>
        </li>
      ))}
    </ul>
  )
}

function TestResult({ ok, error, sample }: { ok: boolean; error: string | null; sample: string[] }) {
  if (!ok) return <span role="alert" style={ERROR_TEXT}>연결하지 못했습니다({error}). 주소, 계정, 하위 경로를 확인하세요.</span>
  const found = sample.length > 0 ? `읽은 파일 예: ${sample.join(', ')}` : '읽을 수 있는 파일이 아직 없습니다.'
  return <span role="status" style={MUTED}>연결됐습니다. {found}</span>
}

function Actions({ connector, onDeleted, onSyncRequested }: {
  connector: ConnectorDetail; onDeleted: () => void; onSyncRequested: () => void
}) {
  const sync = useSyncConnector()
  const test = useTestConnector()
  const remove = useDeleteConnector()
  const [isConfirming, setIsConfirming] = useState(false)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 'var(--space-4)' }}>
      <span style={{ display: 'flex', gap: 'var(--space-2)', flexWrap: 'wrap' }}>
        <button type="button" className="krds-btn xsmall primary" disabled={sync.isPending} onClick={() => sync.mutate(connector.id, { onSuccess: onSyncRequested })}>
          <RefreshCw size={14} /> 지금 동기화
        </button>
        <button type="button" className="krds-btn xsmall secondary" disabled={test.isPending} onClick={() => test.mutate(connector.id)}>
          {test.isPending ? <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} /> : <PlugZap size={14} />} 연결 확인
        </button>
        {!isConfirming ? (
          <button type="button" className="krds-btn xsmall tertiary" onClick={() => setIsConfirming(true)}>
            <Trash2 size={14} /> 삭제
          </button>
        ) : (
          <span role="alert" style={{ display: 'inline-flex', gap: 6, alignItems: 'center', fontSize: 12 }}>
            이 연결로 가져온 문서도 모두 지워집니다.
            <button type="button" className="krds-btn xsmall danger" disabled={remove.isPending}
              onClick={() => remove.mutate(connector.id, { onSuccess: onDeleted })}>삭제 확인</button>
            <button type="button" className="krds-btn xsmall text" onClick={() => setIsConfirming(false)}>취소</button>
          </span>
        )}
      </span>
      {sync.isSuccess && <span role="status" style={MUTED}>동기화를 요청했습니다. 결과는 아래 실행 기록에 나타납니다.</span>}
      {sync.isError && <span role="alert" style={ERROR_TEXT}>{errorMessage(sync.error, '동기화를 요청하지 못했습니다.')}</span>}
      {test.data && <TestResult ok={test.data.ok} error={test.data.error} sample={test.data.sample} />}
      {test.isError && <span role="alert" style={ERROR_TEXT}>{errorMessage(test.error, '연결 확인을 요청하지 못했습니다.')}</span>}
      {remove.isError && <span role="alert" style={ERROR_TEXT}>{errorMessage(remove.error, '연결을 삭제하지 못했습니다.')}</span>}
    </div>
  )
}

export default function ConnectorDetailPanel({ connectorId, onDeleted }: { connectorId: string; onDeleted: () => void }) {
  const [pollUntil, setPollUntil] = useState(0)
  const { data: connector, isLoading, isError } = useConnector(connectorId, pollUntil)

  if (isLoading) return <Loader2 size={20} style={{ animation: 'spin 1s linear infinite' }} />
  if (isError || !connector) return <p style={ERROR_TEXT}>연결 정보를 불러오지 못했습니다.</p>

  return (
    <div>
      <h2 style={{ fontSize: 18, fontWeight: 700 }}>{connector.name}</h2>
      <p style={{ ...MUTED, marginBottom: 'var(--space-3)' }}>
        <code>{uncPath(connector)}</code> · 계정 {connector.username} · 컬렉션 {connector.collection_name ?? '-'}
        {' · '}마지막 동기화 {formatDateTime(connector.last_sync_at)}
      </p>
      <Actions connector={connector} onDeleted={onDeleted} onSyncRequested={() => setPollUntil(Date.now() + SYNC_WAIT_MS)} />
      <SettingsForm key={connector.id} connector={connector} />
      <h3 style={{ fontSize: 15, fontWeight: 700, marginBottom: 'var(--space-2)' }}>
        보류·오류 파일 ({connector.held_count + connector.error_count})
      </h3>
      <p style={{ ...MUTED, marginBottom: 'var(--space-2)' }}>
        권한을 그대로 옮길 수 없는 파일은 넓게 열지 않고 보류합니다. 파일 서버에서 권한을 고치면 다음 동기화 때 다시 판단합니다.
      </p>
      <ProblemItems connector={connector} />
      <h3 style={{ fontSize: 15, fontWeight: 700, margin: 'var(--space-5) 0 var(--space-2)' }}>최근 실행</h3>
      <RunHistory connector={connector} />
    </div>
  )
}
