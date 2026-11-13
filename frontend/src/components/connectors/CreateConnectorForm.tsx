import { useState } from 'react'
import { Plus } from 'lucide-react'
import { useCollections } from '../../hooks/useCollections'
import { useConnectorOptions, useCreateConnector } from '../../hooks/useConnectors'
import type { AclMode, ConnectorCreateInput, ConnectorKind, LevelRule } from '../../hooks/useConnectors'
import AclModeField from './AclModeField'
import LevelRulesEditor from './LevelRulesEditor'
import { cleanRules } from './connectorLabels'
import { Alert, Button, Card, ErrorAlert, Field, Input, Segmented, Select } from '../ui'

// 새 원천 연결. 사내 파일 서버(SMB) 공유 폴더나 서버에 마운트한 로컬 폴더를 컬렉션에 잇는다.

interface CreateDraft {
  kind: ConnectorKind
  acl_mode: AclMode
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
  kind: 'smb', acl_mode: 'file_acl', name: '', host: '', share: '', base_path: '', username: '', password: '',
  collection_id: '', sync_interval_minutes: 30, level_rules: [],
}

const KIND_OPTIONS: { value: ConnectorKind; label: string }[] = [
  { value: 'smb', label: '파일 서버(SMB)' },
  { value: 'local', label: '서버 로컬 폴더' },
]

type SmbField = 'host' | 'share' | 'base_path' | 'username' | 'password'

const SMB_FIELDS: { key: SmbField; label: string; placeholder: string; type?: string; isOptional?: boolean }[] = [
  { key: 'host', label: '서버 주소', placeholder: '예: fs01.corp.local' },
  { key: 'share', label: '공유 이름', placeholder: '예: docs' },
  { key: 'base_path', label: '하위 경로(선택)', placeholder: '예: 영업/2027', isOptional: true },
  { key: 'username', label: '서비스 계정', placeholder: '예: svc-docvec@corp.local' },
  { key: 'password', label: '비밀번호', placeholder: '', type: 'password' },
]

const FIELD_GRID: React.CSSProperties = { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 'var(--space-3)' }
const MIN_INTERVAL = 5

function isDraftReady(draft: CreateDraft): boolean {
  const hasCommon = !!draft.name.trim() && !!draft.collection_id
    && Number.isInteger(draft.sync_interval_minutes) && draft.sync_interval_minutes >= MIN_INTERVAL
  if (!hasCommon) return false
  if (draft.kind === 'local') return !!draft.base_path
  return SMB_FIELDS.every((f) => f.isOptional || draft[f.key].trim())
}

function toInput(draft: CreateDraft): ConnectorCreateInput {
  const common = {
    name: draft.name.trim(),
    collection_id: draft.collection_id,
    sync_interval_minutes: draft.sync_interval_minutes,
    level_rules: cleanRules(draft.level_rules),
  }
  if (draft.kind === 'local') {
    return { ...common, kind: 'local', acl_mode: 'collection_only', base_path: draft.base_path }
  }
  return {
    ...common, kind: 'smb', acl_mode: draft.acl_mode, host: draft.host.trim(), share: draft.share.trim(),
    base_path: draft.base_path.trim(), username: draft.username.trim(), password: draft.password,
  }
}

function LocalFolderFields({ draft, onChange }: { draft: CreateDraft; onChange: (folder: string) => void }) {
  const options = useConnectorOptions()
  const folders = options.data?.local_folders ?? []
  return (
    <>
      <Field label="폴더" hint={options.data ? `서버의 ${options.data.local_root} 아래 폴더입니다.` : undefined}>
        {(id) => (
          <Select id={id} controlSize="sm" value={draft.base_path} onChange={(e) => onChange(e.target.value)}>
            <option value="">폴더 선택…</option>
            {folders.map((name) => <option key={name} value={name}>{name}</option>)}
          </Select>
        )}
      </Field>
      {options.data && folders.length === 0 && (
        <Alert tone="info">
          아직 고를 폴더가 없습니다. 서버의 원천 폴더({options.data.local_root}, 호스트에서는 CONNECTOR_LOCAL_DIR)에
          하위 폴더를 만들고 문서를 넣은 뒤 다시 여세요.
        </Alert>
      )}
    </>
  )
}

export default function CreateConnectorForm({ onCreated }: { onCreated: (id: string) => void }) {
  const create = useCreateConnector()
  const collections = useCollections()
  const options = useConnectorOptions()
  const [draft, setDraft] = useState<CreateDraft>(EMPTY_DRAFT)
  const isReady = isDraftReady(draft)

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!isReady) return
    create.mutate(toInput(draft), { onSuccess: (created) => { setDraft(EMPTY_DRAFT); onCreated(created.id) } })
  }

  return (
    <Card title="새 원천 연결">
      <form onSubmit={handleSubmit} aria-label="새 원천 연결" style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
        <Segmented
          label="원천 종류"
          options={KIND_OPTIONS}
          value={draft.kind}
          onChange={(kind) => setDraft({ ...draft, kind, base_path: '' })}
        />
        <div style={FIELD_GRID}>
          <Field label="이름">
            {(id) => (
              <Input id={id} controlSize="sm" value={draft.name} placeholder="예: 영업부 공유 폴더" autoComplete="off"
                onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
            )}
          </Field>
          {draft.kind === 'smb' ? SMB_FIELDS.map((f) => (
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
          )) : (
            <LocalFolderFields draft={draft} onChange={(base_path) => setDraft({ ...draft, base_path })} />
          )}
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
              <Input id={id} controlSize="sm" type="number" min={MIN_INTERVAL} max={10080} value={draft.sync_interval_minutes}
                onChange={(e) => setDraft({ ...draft, sync_interval_minutes: Number(e.target.value) })} />
            )}
          </Field>
        </div>
        {draft.kind === 'smb' ? (
          <AclModeField
            value={draft.acl_mode}
            onChange={(acl_mode) => setDraft({ ...draft, acl_mode })}
            hasDirectory={options.data?.directory_login ?? true}
          />
        ) : (
          <Alert tone="warning">
            로컬 폴더에는 파일 권한 정보가 없어 컬렉션 권한만 적용합니다. 이 컬렉션을 볼 수 있는 사람은 가져온 문서를 모두 봅니다.
          </Alert>
        )}
        <LevelRulesEditor rules={draft.level_rules} onChange={(level_rules) => setDraft({ ...draft, level_rules })} disabled={create.isPending} />
        <div style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'center', flexWrap: 'wrap' }}>
          <Button type="submit" variant="primary" size="sm" disabled={!isReady || create.isPending} icon={<Plus size={14} aria-hidden="true" />}>
            연결 추가
          </Button>
          {draft.kind === 'smb' && (
            <span className="ds-cell-muted" style={{ fontSize: 'var(--text-xs)' }}>비밀번호는 암호화해 저장하며 다시 보여 주지 않습니다.</span>
          )}
        </div>
        {create.isError && <ErrorAlert error={create.error} message="연결을 추가하지 못했습니다." />}
      </form>
    </Card>
  )
}
