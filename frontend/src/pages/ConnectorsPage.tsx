import { useState } from 'react'
import { Loader2, Plus, ShieldOff } from 'lucide-react'
import { useCollections } from '../hooks/useCollections'
import { useConnectors, useCreateConnector } from '../hooks/useConnectors'
import type { Connector, LevelRule } from '../hooks/useConnectors'
import { useAuthStore } from '../store/authStore'
import ConnectorDetailPanel from '../components/connectors/ConnectorDetailPanel'
import LevelRulesEditor from '../components/connectors/LevelRulesEditor'
import { STATUS_BADGE, STATUS_LABELS, cleanRules, errorMessage, formatDateTime } from '../components/connectors/connectorLabels'

// v3 마일스톤 3 — 사내 파일 서버(SMB)를 컬렉션에 연결한다(관리자 전용).
// 파일 서버의 권한을 그대로 옮기므로, 여기서 가져온 문서의 접근 권한은 문서 화면에서 고칠 수 없다.

const ERROR_BOX: React.CSSProperties = {
  background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 'var(--radius-md)',
  padding: 'var(--space-3)', color: '#dc2626', fontSize: 13, marginBottom: 'var(--space-3)',
}
const INPUT: React.CSSProperties = { fontSize: 13, padding: '4px 8px', border: '1px solid #e2e8f0', borderRadius: 4 }
const FIELD: React.CSSProperties = { display: 'flex', flexDirection: 'column', gap: 4, fontSize: 13 }

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
    <form onSubmit={handleSubmit} aria-label="새 원천 연결"
      style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)', padding: 'var(--space-4)', border: '1px solid #e2e8f0', borderRadius: 'var(--radius-md)', marginBottom: 'var(--space-5)' }}>
      <span style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 'var(--space-3)' }}>
        {TEXT_FIELDS.map((f) => (
          <label key={f.key} style={FIELD}>
            {f.label}
            <input style={INPUT} type={f.type ?? 'text'} value={draft[f.key]} placeholder={f.placeholder}
              autoComplete={f.type === 'password' ? 'new-password' : 'off'}
              onChange={(e) => setDraft({ ...draft, [f.key]: e.target.value })} />
          </label>
        ))}
        <label style={FIELD}>
          넣을 컬렉션
          <select style={INPUT} value={draft.collection_id} onChange={(e) => setDraft({ ...draft, collection_id: e.target.value })}>
            <option value="">컬렉션 선택…</option>
            {(collections.data?.items ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </label>
        <label style={FIELD}>
          동기화 주기(분)
          <input style={INPUT} type="number" min={5} max={10080} value={draft.sync_interval_minutes}
            onChange={(e) => setDraft({ ...draft, sync_interval_minutes: Number(e.target.value) })} />
        </label>
      </span>
      <LevelRulesEditor rules={draft.level_rules} onChange={(level_rules) => setDraft({ ...draft, level_rules })} disabled={create.isPending} />
      <span style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'center' }}>
        <button type="submit" className="krds-btn small primary" disabled={!isReady || create.isPending}>
          <Plus size={14} /> 연결 추가
        </button>
        <span style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>비밀번호는 암호화해 저장하며 다시 보여 주지 않습니다.</span>
      </span>
      {create.isError && <div style={ERROR_BOX}>{errorMessage(create.error, '연결을 추가하지 못했습니다. 입력값을 확인하세요.')}</div>}
    </form>
  )
}

function ConnectorList({ connectors, selectedId, onSelect }: {
  connectors: Connector[]; selectedId: string | null; onSelect: (id: string) => void
}) {
  if (connectors.length === 0) {
    return <p style={{ color: 'var(--color-text-muted)', fontSize: 13 }}>아직 연결한 파일 서버가 없습니다.</p>
  }
  return (
    <ul aria-label="원천 연결 목록" style={{ listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: 4 }}>
      {connectors.map((c) => {
        const isSelected = c.id === selectedId
        return (
          <li key={c.id}>
            <button type="button" aria-current={isSelected ? 'true' : undefined} onClick={() => onSelect(c.id)}
              style={{
                width: '100%', textAlign: 'left', padding: 'var(--space-2) var(--space-3)', borderRadius: 'var(--radius-md)', cursor: 'pointer',
                border: isSelected ? '1px solid var(--color-primary, #256ef4)' : '1px solid #e2e8f0',
                background: isSelected ? 'var(--color-primary-light, #eef4ff)' : 'transparent',
              }}>
              <span style={{ display: 'flex', alignItems: 'center', gap: 6, fontWeight: 600, fontSize: 14 }}>
                {c.name}
                {!c.enabled && <span className="krds-badge xsmall bg-gray">꺼짐</span>}
                {c.last_status && <span className={`krds-badge xsmall ${STATUS_BADGE[c.last_status]}`}>{STATUS_LABELS[c.last_status]}</span>}
              </span>
              <span style={{ display: 'block', fontSize: 12, color: 'var(--color-text-muted)' }}>
                {c.collection_name ?? '-'} · 마지막 {formatDateTime(c.last_sync_at)}
                {c.held_count > 0 && ` · 보류 ${c.held_count}`}
                {c.error_count > 0 && ` · 오류 ${c.error_count}`}
              </span>
            </button>
          </li>
        )
      })}
    </ul>
  )
}

export default function ConnectorsPage() {
  const currentUser = useAuthStore((s) => s.user)
  const { data, isLoading, isError } = useConnectors()
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [isCreating, setIsCreating] = useState(false)

  if (currentUser?.role !== 'admin') {
    return (
      <div style={{ textAlign: 'center', padding: 'var(--space-8)', color: 'var(--color-text-muted)' }}>
        <ShieldOff size={48} style={{ margin: '0 auto var(--space-4)', display: 'block', opacity: 0.4 }} />
        <p>관리자만 접근할 수 있습니다.</p>
      </div>
    )
  }

  return (
    <div>
      <style>{'@keyframes spin { to { transform: rotate(360deg) } }'}</style>
      <div style={{ marginBottom: 'var(--space-5)', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 'var(--space-4)' }}>
        <div>
          <h1 style={{ fontSize: 24, fontWeight: 700 }}>문서 원천 연결</h1>
          <p style={{ fontSize: 13, color: 'var(--color-text-muted)', marginTop: 4 }}>
            사내 파일 서버의 문서를 파일 권한 그대로 가져옵니다. 파일 서버에서 권한이나 내용이 바뀌면 다음 동기화 때 반영됩니다.
          </p>
        </div>
        <button type="button" className="krds-btn small secondary" aria-expanded={isCreating} onClick={() => setIsCreating((v) => !v)}>
          {isCreating ? '닫기' : '새 연결'}
        </button>
      </div>

      {isCreating && <CreateConnectorForm onCreated={(id) => { setIsCreating(false); setSelectedId(id) }} />}

      {isLoading && <Loader2 size={24} style={{ animation: 'spin 1s linear infinite' }} />}
      {isError && <div style={ERROR_BOX}>원천 연결 목록을 불러오지 못했습니다.</div>}

      {!isLoading && !isError && (
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(220px, 300px) 1fr', gap: 'var(--space-6)', alignItems: 'start' }}>
          <ConnectorList connectors={data ?? []} selectedId={selectedId} onSelect={setSelectedId} />
          <section aria-label="원천 연결 상세">
            {selectedId ? (
              <ConnectorDetailPanel key={selectedId} connectorId={selectedId} onDeleted={() => setSelectedId(null)} />
            ) : (
              <p style={{ color: 'var(--color-text-muted)', fontSize: 13 }}>왼쪽에서 연결을 선택하세요.</p>
            )}
          </section>
        </div>
      )}
    </div>
  )
}
