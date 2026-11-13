import { useEffect, useState } from 'react'
import { NavLink, Outlet, useParams } from 'react-router-dom'
import { Settings, Pencil, Check, UserPlus, UserMinus, Loader2, Bot, RotateCcw, Info, Users as UsersIcon, KeyRound, Trash2 } from 'lucide-react'
import {
  useProject,
  useUpdateProject,
  useSetProjectSystemPrompt,
  useProjectMembers,
  useInviteProjectMember,
  useRemoveProjectMember,
  useProjectApiKeys,
  useSetProjectApiKey,
  useDeleteProjectApiKey,
} from '../hooks/useProjects'
import { useChatModels } from '../hooks/useChat'
import { Alert, Badge, Button, ErrorAlert, Field, IconButton, Input, Modal, Page, PageBody, PageHeader, Select, Spinner, Tabs, Textarea } from '../components/ui'
import { describeError } from '../lib/apiError'

const API_KEY_PROVIDER_LABELS: Record<string, string> = {
  openai: 'OpenAI',
  anthropic: 'Anthropic',
}

const ROLE_LABELS: Record<string, string> = { owner: '소유자', editor: '편집자', viewer: '조회자' }

const TABS = [
  { to: 'collections', label: '컬렉션' },
  { to: 'documents', label: '문서' },
  { to: 'search', label: '검색' },
  { to: 'chat', label: '채팅' },
  { to: 'workflows', label: '워크플로우' },
]

type SettingsTab = 'info' | 'members' | 'ai'

const SETTINGS_TAB_ITEMS: ReadonlyArray<{ value: SettingsTab; label: React.ReactNode }> = [
  { value: 'info', label: <span style={{ display: 'inline-flex', alignItems: 'center', gap: 'var(--space-1)' }}><Info size={14} aria-hidden="true" />기본정보</span> },
  { value: 'members', label: <span style={{ display: 'inline-flex', alignItems: 'center', gap: 'var(--space-1)' }}><UsersIcon size={14} aria-hidden="true" />멤버</span> },
  { value: 'ai', label: <span style={{ display: 'inline-flex', alignItems: 'center', gap: 'var(--space-1)' }}><Bot size={14} aria-hidden="true" />AI 관리</span> },
]

export default function ProjectWorkspace() {
  const { projectId } = useParams<{ projectId: string }>()
  const { data: project, isLoading, isError, error, refetch } = useProject(projectId ?? null)
  const [showSettings, setShowSettings] = useState(false)

  if (isError) {
    return (
      <Page>
        <PageBody>
          <ErrorAlert error={error} message="프로젝트를 불러오지 못했습니다." onRetry={() => refetch()} />
        </PageBody>
      </Page>
    )
  }
  if (isLoading || !project) {
    return <Spinner />
  }

  return (
    <Page>
      <PageHeader
        title={project.name}
        actions={
          <IconButton label="프로젝트 설정" onClick={() => setShowSettings(true)}>
            <Settings size={16} aria-hidden="true" />
          </IconButton>
        }
      />

      <nav aria-label="프로젝트 메뉴" style={{ display: 'flex', gap: 'var(--space-1)', borderBottom: '1px solid var(--color-border)', marginBottom: 'var(--space-5)' }}>
        {TABS.map((t) => (
          <NavLink
            key={t.to}
            to={t.to}
            style={({ isActive }) => ({
              padding: 'var(--space-2) var(--space-3)',
              fontSize: 'var(--text-sm)',
              textDecoration: 'none',
              color: isActive ? 'var(--color-primary)' : 'var(--color-text-muted)',
              borderBottom: isActive ? '2px solid var(--color-primary)' : '2px solid transparent',
              fontWeight: isActive ? 600 : 400,
            })}
          >
            {t.label}
          </NavLink>
        ))}
      </nav>

      <div style={{ flex: '1 1 auto', minHeight: 0 }}>
        <Outlet />
      </div>

      {showSettings && (
        <ProjectSettingsModal projectId={project.id} onClose={() => setShowSettings(false)} />
      )}
    </Page>
  )
}

function ProjectSettingsModal({ projectId, onClose }: { projectId: string; onClose: () => void }) {
  const { data: project } = useProject(projectId)
  const [tab, setTab] = useState<SettingsTab>('info')

  if (!project) return null

  return (
    <Modal
      isOpen
      size="lg"
      isDismissible={false}
      title="프로젝트 설정"
      onClose={onClose}
      footer={<Button variant="secondary" onClick={onClose}>닫기</Button>}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
        <p style={{ margin: 0, fontSize: 'var(--text-sm)', color: 'var(--color-text-muted)' }}>{project.name}</p>
        <Tabs
          items={SETTINGS_TAB_ITEMS}
          value={tab}
          onChange={setTab}
          label="프로젝트 설정 항목"
          idPrefix="project-settings"
        />
        <div role="tabpanel" id="project-settings-panel-info" aria-labelledby="project-settings-tab-info" hidden={tab !== 'info'}>
          {tab === 'info' && <ProjectInfoTab projectId={projectId} />}
        </div>
        <div role="tabpanel" id="project-settings-panel-members" aria-labelledby="project-settings-tab-members" hidden={tab !== 'members'}>
          {tab === 'members' && <ProjectMembersTab projectId={projectId} />}
        </div>
        <div role="tabpanel" id="project-settings-panel-ai" aria-labelledby="project-settings-tab-ai" hidden={tab !== 'ai'}>
          {tab === 'ai' && <ProjectAiTab projectId={projectId} />}
        </div>
      </div>
    </Modal>
  )
}

function ProjectInfoTab({ projectId }: { projectId: string }) {
  const { data: project } = useProject(projectId)
  const updateProject = useUpdateProject()
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    if (!saved) return undefined
    const timer = setTimeout(() => setSaved(false), 2000)
    return () => clearTimeout(timer)
  }, [saved])

  if (!project) return null

  const startEdit = () => {
    setName(project.name)
    setDescription(project.description ?? '')
    setEditing(true)
  }
  const handleSave = (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim()) return
    updateProject.mutate(
      { id: projectId, name: name.trim(), description: description.trim() || undefined },
      { onSuccess: () => { setEditing(false); setSaved(true) } },
    )
  }

  if (!editing) {
    return (
      <div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
          <p style={{ margin: 0, fontSize: 'var(--text-lg)', fontWeight: 600 }}>{project.name}</p>
          {project.is_owner && (
            <IconButton label="수정" onClick={startEdit}><Pencil size={14} aria-hidden="true" /></IconButton>
          )}
        </div>
        <p style={{ margin: 'var(--space-2) 0 0', fontSize: 'var(--text-sm)', color: 'var(--color-text-muted)' }}>
          {project.description || '설명이 없습니다.'}
        </p>
        {saved && <p role="status" style={{ fontSize: 'var(--text-xs)', color: 'var(--color-success)', margin: 'var(--space-2) 0 0' }}>저장되었습니다.</p>}
      </div>
    )
  }

  return (
    <form onSubmit={handleSave} style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
      <Field label="프로젝트 이름">
        {(id) => <Input id={id} autoFocus value={name} onChange={(e) => setName(e.target.value)} />}
      </Field>
      <Field label="설명">
        {(id) => (
          <Textarea id={id} value={description} onChange={(e) => setDescription(e.target.value)} rows={2} placeholder="설명 (선택 사항)" />
        )}
      </Field>
      <div style={{ display: 'flex', gap: 'var(--space-2)' }}>
        <Button type="submit" variant="primary" size="sm" disabled={updateProject.isPending}>저장</Button>
        <Button variant="secondary" size="sm" onClick={() => { updateProject.reset(); setEditing(false) }}>취소</Button>
      </div>
      {updateProject.isError && <ErrorAlert error={updateProject.error} message="프로젝트 정보를 저장하지 못했습니다." />}
    </form>
  )
}

function ProjectMembersTab({ projectId }: { projectId: string }) {
  const { data: project } = useProject(projectId)
  const { data: memberData, isError: isMembersError, error: membersError, refetch: refetchMembers } = useProjectMembers(projectId)
  const inviteMember = useInviteProjectMember()
  const removeMember = useRemoveProjectMember()

  const [inviteEmail, setInviteEmail] = useState('')
  const [inviteRole, setInviteRole] = useState<'viewer' | 'editor'>('viewer')
  const [inviteError, setInviteError] = useState<string | null>(null)
  const [confirmRemoveUserId, setConfirmRemoveUserId] = useState<string | null>(null)

  if (!project) return null

  const handleInvite = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!inviteEmail.trim()) return
    setInviteError(null)
    try {
      await inviteMember.mutateAsync({ projectId, email: inviteEmail.trim(), role: inviteRole })
      setInviteEmail('')
      setInviteRole('viewer')
    } catch (err) {
      setInviteError(describeError(err, '초대하지 못했습니다.'))
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
      {project.is_owner && (
        <form onSubmit={handleInvite} style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--space-2)' }}>
          <Input
            type="email"
            aria-label="초대할 이메일"
            value={inviteEmail}
            onChange={(e) => setInviteEmail(e.target.value)}
            placeholder="user@example.com"
            style={{ flex: '1 1 auto' }}
            required
          />
          <Select
            aria-label="초대할 권한"
            style={{ flex: '0 0 128px', width: 128 }}
            value={inviteRole}
            onChange={(e) => setInviteRole(e.target.value as 'viewer' | 'editor')}
          >
            <option value="viewer">조회자</option>
            <option value="editor">편집자</option>
          </Select>
          <Button
            type="submit"
            variant="primary"
            size="sm"
            disabled={inviteMember.isPending || !inviteEmail.trim()}
            icon={inviteMember.isPending
              ? <Loader2 size={14} aria-hidden="true" style={{ animation: 'spin 1s linear infinite' }} />
              : <UserPlus size={14} aria-hidden="true" />}
          >
            초대
          </Button>
        </form>
      )}
      {inviteError && <Alert tone="danger">{inviteError}</Alert>}
      {removeMember.isError && <ErrorAlert error={removeMember.error} message="멤버를 제거하지 못했습니다." />}
      {isMembersError && <ErrorAlert error={membersError} message="멤버 목록을 불러오지 못했습니다." onRetry={() => refetchMembers()} />}
      <p style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-muted)', margin: 0, lineHeight: 1.6 }}>
        프로젝트 멤버는 이 프로젝트에 속한 모든 컬렉션·문서·채팅에 자동으로 접근합니다.
        특정 컬렉션에서 일부 멤버를 제외하려면 해당 컬렉션의 공유 설정에서 접근 범위를 제한하세요.
      </p>
      <div className="ds-table-wrap">
        <table className="ds-table ds-table--compact" aria-label="프로젝트 멤버">
          <thead>
            <tr>
              <th scope="col">사용자</th>
              <th scope="col">권한</th>
              <th scope="col"><span className="sr-only">작업</span></th>
            </tr>
          </thead>
          <tbody>
            {memberData?.items.map((m) => (
              <tr key={m.user_id}>
                <td>
                  {m.username || m.email}
                  <span className="ds-cell-sub">{m.email}</span>
                </td>
                <td><Badge tone="info">{ROLE_LABELS[m.role] ?? m.role}</Badge></td>
                <td>
                  {m.role !== 'owner' && project.is_owner && (
                    confirmRemoveUserId === m.user_id ? (
                      <span style={{ display: 'inline-flex', gap: 'var(--space-2)', alignItems: 'center', whiteSpace: 'nowrap' }}>
                        <span style={{ fontSize: 'var(--text-xs)', color: 'var(--color-danger)' }}>제거할까요?</span>
                        <Button size="sm" variant="danger" onClick={() => {
                          removeMember.mutate({ projectId, userId: m.user_id })
                          setConfirmRemoveUserId(null)
                        }}>
                          확인
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => setConfirmRemoveUserId(null)}>취소</Button>
                      </span>
                    ) : (
                      <IconButton label="멤버 제거" tone="danger" onClick={() => setConfirmRemoveUserId(m.user_id)}>
                        <UserMinus size={16} aria-hidden="true" />
                      </IconButton>
                    )
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function ProjectAiTab({ projectId }: { projectId: string }) {
  const { data: project } = useProject(projectId)
  const { data: modelsData } = useChatModels()
  const setSystemPrompt = useSetProjectSystemPrompt()
  const [value, setValue] = useState('')
  const [initialized, setInitialized] = useState(false)
  const [saved, setSaved] = useState(false)

  const defaultPrompt = modelsData?.default_system_prompt ?? ''

  useEffect(() => {
    if (project && !initialized) {
      setValue(project.system_prompt ?? '')
      setInitialized(true)
    }
  }, [project, initialized])

  if (!project) return null

  const handleSave = () => {
    setSystemPrompt.mutate({ id: projectId, systemPrompt: value.trim() }, {
      onSuccess: () => {
        setSaved(true)
        setTimeout(() => setSaved(false), 2000)
      },
    })
  }
  const handleReset = () => {
    setValue('')
    setSystemPrompt.mutate({ id: projectId, systemPrompt: null })
  }

  if (!project.is_owner) {
    return (
      <div>
        <p style={{ fontSize: 'var(--text-sm)', color: 'var(--color-text-muted)', margin: '0 0 var(--space-3)' }}>
          이 프로젝트의 AI 지침은 소유자만 수정할 수 있습니다.
        </p>
        <pre style={{
          margin: 0, padding: 'var(--space-3)', background: 'var(--color-surface-subtle)', borderRadius: 'var(--radius-md)',
          fontSize: 'var(--text-sm)', whiteSpace: 'pre-wrap', fontFamily: 'inherit',
        }}>
          {project.system_prompt || defaultPrompt || '기본 지침을 사용합니다.'}
        </pre>
      </div>
    )
  }

  return (
    <div>
      <Field label="AI 지침" hint="이 프로젝트 안에서의 채팅에 사용할 AI 지침입니다. 비워두면 개인 지침 또는 기본 지침이 사용됩니다.">
        {(id) => (
          <Textarea
            id={id}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            rows={10}
            placeholder={defaultPrompt}
            style={{ resize: 'vertical', lineHeight: 1.5 }}
          />
        )}
      </Field>
      <div style={{ display: 'flex', gap: 'var(--space-2)', marginTop: 'var(--space-2)' }}>
        <Button variant="primary" size="sm" onClick={handleSave} disabled={setSystemPrompt.isPending}
          icon={saved ? <Check size={14} aria-hidden="true" /> : undefined}>
          저장
        </Button>
        {!!project.system_prompt && (
          <Button variant="ghost" size="sm" onClick={handleReset} disabled={setSystemPrompt.isPending}
            icon={<RotateCcw size={14} aria-hidden="true" />}>
            기본값으로 초기화
          </Button>
        )}
      </div>
      {setSystemPrompt.isError && <ErrorAlert error={setSystemPrompt.error} message="AI 지침을 저장하지 못했습니다." />}

      <ProjectApiKeySection projectId={projectId} />
    </div>
  )
}

function ProjectApiKeySection({ projectId }: { projectId: string }) {
  const { data, isLoading, isError, error, refetch } = useProjectApiKeys(projectId)
  const setApiKey = useSetProjectApiKey()
  const deleteApiKey = useDeleteProjectApiKey()
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [savedProvider, setSavedProvider] = useState<string | null>(null)

  const handleSave = (provider: string) => {
    const apiKey = (drafts[provider] || '').trim()
    if (!apiKey) return
    setApiKey.mutate(
      { projectId, provider, apiKey },
      {
        onSuccess: () => {
          setDrafts((d) => ({ ...d, [provider]: '' }))
          setSavedProvider(provider)
          setTimeout(() => setSavedProvider(null), 2000)
        },
      }
    )
  }

  return (
    <section style={{ marginTop: 'var(--space-6)', paddingTop: 'var(--space-4)', borderTop: '1px solid var(--color-border)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', marginBottom: 'var(--space-2)' }}>
        <KeyRound size={14} aria-hidden="true" />
        <h3 style={{ fontSize: 'var(--text-sm)', fontWeight: 600, margin: 0 }}>프로젝트 API 키</h3>
      </div>
      <p style={{ fontSize: 'var(--text-sm)', color: 'var(--color-text-muted)', margin: '0 0 var(--space-3)' }}>
        이 프로젝트에서만 사용되는 OpenAI / Anthropic API 키입니다. 등록하면 이 프로젝트의 멤버는
        개인 API 키가 없어도 프로젝트 채팅에서 해당 모델을 사용할 수 있습니다.
      </p>

      {isLoading && <Spinner />}
      {isError && <ErrorAlert error={error} message="프로젝트 API 키를 불러오지 못했습니다." onRetry={() => refetch()} />}
      {setApiKey.isError && <ErrorAlert error={setApiKey.error} message="API 키를 저장하지 못했습니다." />}
      {deleteApiKey.isError && <ErrorAlert error={deleteApiKey.error} message="API 키를 삭제하지 못했습니다." />}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
        {data?.items.map((item) => (
          <div
            key={item.provider}
            style={{ border: '1px solid var(--color-border)', borderRadius: 'var(--radius-md)', padding: 'var(--space-3)' }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 'var(--space-2)' }}>
              <span style={{ fontSize: 'var(--text-sm)', fontWeight: 600 }}>{API_KEY_PROVIDER_LABELS[item.provider] ?? item.provider}</span>
              <Badge tone={item.registered ? 'success' : 'neutral'} hasDot>
                {item.registered ? '등록됨' : '미등록'}
              </Badge>
            </div>

            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--space-2)' }}>
              <Input
                type="password"
                aria-label={`${API_KEY_PROVIDER_LABELS[item.provider] ?? item.provider} API 키`}
                value={drafts[item.provider] || ''}
                onChange={(e) => setDrafts((d) => ({ ...d, [item.provider]: e.target.value }))}
                placeholder={item.registered ? '새 API 키로 교체...' : 'API 키 입력...'}
                controlSize="sm"
                style={{ flex: '1 1 220px' }}
              />
              <Button
                size="sm"
                variant="primary"
                onClick={() => handleSave(item.provider)}
                disabled={setApiKey.isPending || !(drafts[item.provider] || '').trim()}
                icon={savedProvider === item.provider ? <Check size={14} aria-hidden="true" /> : undefined}
              >
                저장
              </Button>
              {item.registered && (
                <Button
                  size="sm"
                  variant="danger"
                  onClick={() => deleteApiKey.mutate({ projectId, provider: item.provider })}
                  disabled={deleteApiKey.isPending}
                  icon={<Trash2 size={14} aria-hidden="true" />}
                >
                  삭제
                </Button>
              )}
            </div>
            {item.updated_at && (
              <p style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-muted)', margin: 'var(--space-2) 0 0' }}>
                마지막 업데이트: {new Date(item.updated_at).toLocaleString('ko-KR')}
              </p>
            )}
          </div>
        ))}
      </div>
    </section>
  )
}
