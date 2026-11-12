import { useState } from 'react'
import { Plus, ShieldOff } from 'lucide-react'
import { useCollections } from '../hooks/useCollections'
import { useConnectors, useCreateConnector } from '../hooks/useConnectors'
import type { Connector, LevelRule } from '../hooks/useConnectors'
import { useAuthStore } from '../store/authStore'
import ConnectorDetailPanel from '../components/connectors/ConnectorDetailPanel'
import LevelRulesEditor from '../components/connectors/LevelRulesEditor'
import { STATUS_LABELS, STATUS_TONE, cleanRules, errorMessage, formatDateTime } from '../components/connectors/connectorLabels'
import {
  Alert, Badge, Button, Card, EmptyState, Field, Input, Page, PageBody, PageHeader, Select, Spinner, Split, Stat, StatStrip, Toolbar,
} from '../components/ui'

// v3 마일스톤 3 — 사내 파일 서버(SMB)를 컬렉션에 연결한다(관리자 전용).
// 파일 서버의 권한을 그대로 옮기므로, 여기서 가져온 문서의 접근 권한은 문서 화면에서 고칠 수 없다.

interface CreateDraft {
  name: string
  host: string
  share: string
  base_path: string
  username: string
  password: string
  collection_id: string
  sync_interval_minutes: number
  level_rules: LevelRule[]
}

const EMPTY_DRAFT: CreateDraft = {
  name: '', host: '', share: '', base_path: '', username: '', password: '', collection_id: '',
  sync_interval_minutes: 30, level_rules: [],
}

type TextField = Exclude<keyof CreateDraft, 'sync_interval_minutes' | 'level_rules' | 'collection_id'>

const TEXT_FIELDS: { key: TextField; label: string; placeholder: string; type?: string }[] = [
  { key: 'name', label: '이름', placeholder: '예: 영업부 공유 폴더' },
  { key: 'host', label: '서버 주소', placeholder: '예: fs01.corp.local' },
  { key: 'share', label: '공유 이름', placeholder: '예: docs' },
  { key: 'base_path', label: '하위 경로(선택)', placeholder: '예: 영업/2027' },
  { key: 'username', label: '서비스 계정', placeholder: '예: svc-docvec@corp.local' },
  { key: 'password', label: '비밀번호', placeholder: '', type: 'password' },
]

const FIELD_GRID: React.CSSProperties = { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 'var(--space-3)' }

function CreateConnectorForm({ onCreated }: { onCreated: (id: string) => void }) {
  const create = useCreateConnector()
  const collections = useCollections()
  const [draft, setDraft] = useState<CreateDraft>(EMPTY_DRAFT)
  const isReady = TEXT_FIELDS.every((f) => f.key === 'base_path' || draft[f.key].trim()) && !!draft.collection_id
    && Number.isInteger(draft.sync_interval_minutes) && draft.sync_interval_minutes >= 5

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!isReady) return
    create.mutate(
      {
        ...draft,
        name: draft.name.trim(), host: draft.host.trim(), share: draft.share.trim(),
        base_path: draft.base_path.trim(), username: draft.username.trim(),
        level_rules: cleanRules(draft.level_rules),
      },
      { onSuccess: (created) => { setDraft(EMPTY_DRAFT); onCreated(created.id) } },
    )
  }

  return (
    <Card title="새 원천 연결">
      <form onSubmit={handleSubmit} aria-label="새 원천 연결" style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
        <div style={FIELD_GRID}>
          {TEXT_FIELDS.map((f) => (
            <Field key={f.key} label={f.label}>
              {(id) => (
                <Input
                  id={id}
                  controlSize="sm"
                  type={f.type ?? 'text'}
                  value={draft[f.key]}
                  placeholder={f.placeholder}
                  autoComplete={f.type === 'password' ? 'new-password' : 'off'}
                  onChange={(e) => setDraft({ ...draft, [f.key]: e.target.value })}
                />
              )}
            </Field>
          ))}
          <Field label="넣을 컬렉션">
            {(id) => (
              <Select id={id} controlSize="sm" value={draft.collection_id} onChange={(e) => setDraft({ ...draft, collection_id: e.target.value })}>
                <option value="">컬렉션 선택…</option>
                {(collections.data?.items ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </Select>
            )}
          </Field>
          <Field label="동기화 주기(분)">
            {(id) => (
              <Input
                id={id}
                controlSize="sm"
                type="number"
                min={5}
                max={10080}
                value={draft.sync_interval_minutes}
                onChange={(e) => setDraft({ ...draft, sync_interval_minutes: Number(e.target.value) })}
              />
            )}
          </Field>
        </div>
        <LevelRulesEditor rules={draft.level_rules} onChange={(level_rules) => setDraft({ ...draft, level_rules })} disabled={create.isPending} />
        <div style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'center', flexWrap: 'wrap' }}>
          <Button type="submit" variant="primary" size="sm" disabled={!isReady || create.isPending} icon={<Plus size={14} aria-hidden="true" />}>
            연결 추가
          </Button>
          <span className="ds-cell-muted" style={{ fontSize: 'var(--text-xs)' }}>비밀번호는 암호화해 저장하며 다시 보여 주지 않습니다.</span>
        </div>
        {create.isError && <Alert tone="danger">{errorMessage(create.error, '연결을 추가하지 못했습니다. 입력값을 확인하세요.')}</Alert>}
      </form>
    </Card>
  )
}

function rowClassName(connector: Connector): string | undefined {
  if (connector.last_status === 'failed' || connector.error_count > 0) return 'is-danger'
  if (connector.held_count > 0 || !connector.enabled) return 'is-warning'
  return undefined
}

function ConnectorTable({ connectors, selectedId, onSelect }: {
  connectors: Connector[]; selectedId: string | null; onSelect: (id: string) => void
}) {
  if (connectors.length === 0) {
    return <EmptyState title="아직 연결한 파일 서버가 없습니다." description="새 연결을 추가하면 여기에 나타납니다." />
  }
  return (
    <div className="ds-table-wrap">
      <table className="ds-table ds-table--compact">
        <caption className="sr-only">원천 연결 목록</caption>
        <thead>
          <tr>
            <th scope="col">이름</th>
            <th scope="col">컬렉션</th>
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
  const { data, isLoading, isError } = useConnectors()
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
        subtitle="사내 파일 서버의 문서를 파일 권한 그대로 가져옵니다. 권한이나 내용이 바뀌면 다음 동기화 때 반영됩니다."
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
            {isError && <Alert tone="danger">원천 연결 목록을 불러오지 못했습니다.</Alert>}
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
