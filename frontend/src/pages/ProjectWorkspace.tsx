import { useEffect, useState } from 'react'
import { NavLink, Outlet, useParams } from 'react-router-dom'
import {
  Settings, X, Pencil, Check, UserPlus, UserMinus, Loader2, Bot, RotateCcw, Info, Users as UsersIcon,
  KeyRound, Trash2,
} from 'lucide-react'
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

const API_KEY_PROVIDER_LABELS: Record<string, string> = {
  openai: 'OpenAI',
  anthropic: 'Anthropic',
}

const TABS = [
  { to: 'collections', label: '컬렉션' },
  { to: 'documents', label: '문서' },
  { to: 'search', label: '검색' },
  { to: 'chat', label: '채팅' },
]

export default function ProjectWorkspace() {
  const { projectId } = useParams<{ projectId: string }>()
  const { data: project, isLoading } = useProject(projectId ?? null)
  const [showSettings, setShowSettings] = useState(false)

  if (isLoading || !project) {
    return <div className="krds-spinner" role="status"><span className="sr-only">로딩 중</span></div>
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', marginBottom: 'var(--space-4)' }}>
        <h1 style={{ fontSize: 22, fontWeight: 700, margin: 0 }}>{project.name}</h1>
        <button
          type="button"
          onClick={() => setShowSettings(true)}
          title="프로젝트 설정"
          aria-label="프로젝트 설정"
          style={{
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            width: 28, height: 28, borderRadius: 'var(--radius-md, 8px)',
            color: '#64748b', background: 'transparent', border: 'none', cursor: 'pointer',
          }}
        >
          <Settings size={16} />
        </button>
      </div>

      <nav style={{ display: 'flex', gap: 'var(--space-1)', borderBottom: '1px solid var(--color-border)', marginBottom: 'var(--space-6)' }}>
        {TABS.map((t) => (
          <NavLink
            key={t.to}
            to={t.to}
            style={({ isActive }) => ({
              padding: 'var(--space-2) var(--space-4)',
              fontSize: 14,
              textDecoration: 'none',
              color: isActive ? '#1d4ed8' : 'var(--color-text-muted)',
              borderBottom: isActive ? '2px solid #1d4ed8' : '2px solid transparent',
              fontWeight: isActive ? 600 : 400,
            })}
          >
            {t.label}
          </NavLink>
        ))}
      </nav>

      <div style={{ flex: '1 1 auto', minHeight: 0, overflowY: 'auto' }}>
        <Outlet />
      </div>

      {showSettings && (
        <ProjectSettingsModal projectId={project.id} onClose={() => setShowSettings(false)} />
      )}
    </div>
  )
}

type SettingsTab = 'info' | 'members' | 'ai'

function ProjectSettingsModal({ projectId, onClose }: { projectId: string; onClose: () => void }) {
  const { data: project } = useProject(projectId)
  const [tab, setTab] = useState<SettingsTab>('info')

  if (!project) return null

  const settingsTabs: { key: SettingsTab; label: string; icon: React.ReactNode }[] = [
    { key: 'info', label: '기본정보', icon: <Info size={14} /> },
    { key: 'members', label: '멤버', icon: <UsersIcon size={14} /> },
    { key: 'ai', label: 'AI 관리', icon: <Bot size={14} /> },
  ]

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 50,
    }}>
      <section className="krds-modal fade shown in" role="dialog">
        <div className="modal-dialog modal-md">
          <div className="modal-content">
            <div className="modal-header">
              <h2 className="modal-title">프로젝트 설정</h2>
              <p style={{ margin: 'var(--space-1) 0 0', fontSize: 13, color: 'var(--color-text-muted)' }}>
                {project.name}
              </p>
            </div>
            <div className="modal-conts">
              <div className="conts-area" style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
                <div style={{ display: 'flex', gap: 'var(--space-1)', borderBottom: '1px solid var(--color-border)' }}>
                  {settingsTabs.map((t) => (
                    <button
                      key={t.key}
                      type="button"
                      onClick={() => setTab(t.key)}
                      style={{
                        display: 'flex', alignItems: 'center', gap: 'var(--space-1)',
                        padding: 'var(--space-2) var(--space-3)', fontSize: 13,
                        background: 'none', border: 'none', cursor: 'pointer',
                        color: tab === t.key ? '#1d4ed8' : 'var(--color-text-muted)',
                        borderBottom: tab === t.key ? '2px solid #1d4ed8' : '2px solid transparent',
                        fontWeight: tab === t.key ? 600 : 400,
                      }}
                    >
                      {t.icon}
                      {t.label}
                    </button>
                  ))}
                </div>

                {tab === 'info' && <ProjectInfoTab projectId={projectId} />}
                {tab === 'members' && <ProjectMembersTab projectId={projectId} />}
                {tab === 'ai' && <ProjectAiTab projectId={projectId} />}

                <div className="modal-btn btn-wrap">
                  <button type="button" className="krds-btn medium secondary" onClick={onClose}>
                    닫기
                  </button>
                </div>
              </div>
            </div>
            <button type="button" className="krds-btn medium icon btn-close close-modal" onClick={onClose}>
              <span className="sr-only">닫기</span>
              <X size={20} />
            </button>
          </div>
        </div>
        <div className="modal-back"></div>
      </section>
    </div>
  )
}

function ProjectInfoTab({ projectId }: { projectId: string }) {
  const { data: project } = useProject(projectId)
  const updateProject = useUpdateProject()
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [saved, setSaved] = useState(false)

  if (!project) return null

  const startEdit = () => {
    setName(project.name)
    setDescription(project.description ?? '')
    setEditing(true)
  }
  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim()) return
    await updateProject.mutateAsync({ id: projectId, name: name.trim(), description: description.trim() || undefined })
    setEditing(false)
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  if (!editing) {
    return (
      <div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
          <p style={{ margin: 0, fontSize: 16, fontWeight: 600 }}>{project.name}</p>
          {project.is_owner && (
            <button type="button" onClick={startEdit} style={{ color: '#94a3b8' }} title="수정">
              <Pencil size={14} />
            </button>
          )}
        </div>
        <p style={{ margin: 'var(--space-2) 0 0', fontSize: 13, color: 'var(--color-text-muted)' }}>
          {project.description || '설명이 없습니다.'}
        </p>
        {saved && <p style={{ fontSize: 12, color: '#16a34a', margin: 'var(--space-2) 0 0' }}>저장되었습니다.</p>}
      </div>
    )
  }

  return (
    <form onSubmit={handleSave} style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
      <input autoFocus value={name} onChange={(e) => setName(e.target.value)} className="krds-input" />
      <textarea
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        className="krds-input"
        rows={2}
        placeholder="설명 (선택 사항)"
      />
      <div style={{ display: 'flex', gap: 'var(--space-2)' }}>
        <button type="submit" className="krds-btn small primary" disabled={updateProject.isPending}>저장</button>
        <button type="button" className="krds-btn small secondary" onClick={() => setEditing(false)}>취소</button>
      </div>
    </form>
  )
}

function ProjectMembersTab({ projectId }: { projectId: string }) {
  const { data: project } = useProject(projectId)
  const { data: memberData } = useProjectMembers(projectId)
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
    } catch {
      setInviteError('초대에 실패했습니다. 가입된 사용자의 이메일인지 확인하세요.')
    }
  }

  return (
    <div>
      {project.is_owner && (
        <form onSubmit={handleInvite} style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--space-2)', marginBottom: 'var(--space-3)' }}>
          <input
            type="email"
            value={inviteEmail}
            onChange={(e) => setInviteEmail(e.target.value)}
            placeholder="user@example.com"
            className="krds-input"
            style={{ flex: '1 1 auto' }}
            required
          />
          <select
            className="krds-form-select"
            style={{ flex: '0 0 128px', width: 128 }}
            value={inviteRole}
            onChange={(e) => setInviteRole(e.target.value as 'viewer' | 'editor')}
          >
            <option value="viewer">조회자</option>
            <option value="editor">편집자</option>
          </select>
          <button
            type="submit"
            className="krds-btn small primary"
            disabled={inviteMember.isPending || !inviteEmail.trim()}
            style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-1)' }}
          >
            {inviteMember.isPending
              ? <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} />
              : <UserPlus size={14} />}
            초대
          </button>
        </form>
      )}
      {inviteError && (
        <p style={{ fontSize: 13, color: '#dc2626', marginBottom: 'var(--space-3)' }}>{inviteError}</p>
      )}
      <p style={{ fontSize: 12, color: 'var(--color-text-muted)', margin: '0 0 var(--space-3)', lineHeight: 1.6 }}>
        프로젝트 멤버는 이 프로젝트에 속한 모든 컬렉션·문서·채팅에 자동으로 접근합니다.
        특정 컬렉션에서 일부 멤버를 제외하려면 해당 컬렉션의 공유 설정에서 접근 범위를 제한하세요.
      </p>
      <ul style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)', margin: 0, padding: 0, listStyle: 'none' }}>
        {memberData?.items.map((m) => (
          <li
            key={m.user_id}
            style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              padding: 'var(--space-2) var(--space-3)', border: '1px solid #e2e8f0',
              borderRadius: 'var(--radius-md)', background: '#fff',
            }}
          >
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: 14, fontWeight: 500 }}>{m.username || m.email}</div>
              <div style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>{m.email}</div>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', flexShrink: 0 }}>
              {confirmRemoveUserId === m.user_id ? (
                <>
                  <span style={{ fontSize: 12, color: '#dc2626', whiteSpace: 'nowrap' }}>제거할까요?</span>
                  <button
                    type="button"
                    onClick={() => { removeMember.mutate({ projectId, userId: m.user_id }); setConfirmRemoveUserId(null) }}
                    className="krds-btn xsmall primary"
                  >확인</button>
                  <button
                    type="button"
                    onClick={() => setConfirmRemoveUserId(null)}
                    className="krds-btn xsmall secondary"
                  >취소</button>
                </>
              ) : (
                <>
                  <span className="krds-badge xsmall bg-information">
                    {m.role === 'owner' ? '소유자' : m.role === 'editor' ? '편집자' : '조회자'}
                  </span>
                  {m.role !== 'owner' && project.is_owner && (
                    <button
                      type="button"
                      onClick={() => setConfirmRemoveUserId(m.user_id)}
                      style={{ color: '#94a3b8' }}
                      title="멤버 제거"
                      aria-label="멤버 제거"
                    >
                      <UserMinus size={16} />
                    </button>
                  )}
                </>
              )}
            </div>
          </li>
        ))}
      </ul>
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
        <p style={{ fontSize: 13, color: 'var(--color-text-muted)', margin: '0 0 var(--space-3)' }}>
          이 프로젝트의 AI 지침은 소유자만 수정할 수 있습니다.
        </p>
        <pre style={{
          margin: 0, padding: 'var(--space-3)', background: '#f8fafc', borderRadius: 'var(--radius-md)',
          fontSize: 13, whiteSpace: 'pre-wrap', fontFamily: 'inherit',
        }}>
          {project.system_prompt || defaultPrompt || '기본 지침을 사용합니다.'}
        </pre>
      </div>
    )
  }

  return (
    <div>
      <p style={{ fontSize: 13, color: 'var(--color-text-muted)', margin: '0 0 var(--space-3)' }}>
        이 프로젝트 안에서의 채팅에 사용할 AI 지침입니다. 비워두면 개인 지침 또는 기본 지침이 사용됩니다.
      </p>
      <textarea
        value={value}
        onChange={(e) => setValue(e.target.value)}
        rows={10}
        placeholder={defaultPrompt}
        className="krds-input small"
        style={{ width: '100%', resize: 'vertical', fontFamily: 'inherit', lineHeight: 1.5 }}
      />
      <div style={{ display: 'flex', gap: 'var(--space-2)', marginTop: 'var(--space-2)' }}>
        <button
          type="button"
          onClick={handleSave}
          disabled={setSystemPrompt.isPending}
          className="krds-btn small primary"
        >
          {saved ? <Check size={14} /> : null}
          저장
        </button>
        {!!project.system_prompt && (
          <button
            type="button"
            onClick={handleReset}
            disabled={setSystemPrompt.isPending}
            className="krds-btn small text"
          >
            <RotateCcw size={14} />
            기본값으로 초기화
          </button>
        )}
      </div>

      <ProjectApiKeySection projectId={projectId} />
    </div>
  )
}

function ProjectApiKeySection({ projectId }: { projectId: string }) {
  const { data, isLoading } = useProjectApiKeys(projectId)
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
    <div style={{ marginTop: 'var(--space-6)', paddingTop: 'var(--space-4)', borderTop: '1px solid var(--color-border)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', marginBottom: 'var(--space-2)' }}>
        <KeyRound size={14} />
        <span style={{ fontSize: 14, fontWeight: 600 }}>프로젝트 API 키</span>
      </div>
      <p style={{ fontSize: 13, color: 'var(--color-text-muted)', margin: '0 0 var(--space-3)' }}>
        이 프로젝트에서만 사용되는 OpenAI / Anthropic API 키입니다. 등록하면 이 프로젝트의 멤버는
        개인 API 키가 없어도 프로젝트 채팅에서 해당 모델을 사용할 수 있습니다.
      </p>

      {isLoading && <div className="krds-spinner" role="status"><span className="sr-only">로딩 중</span></div>}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
        {data?.items.map((item) => (
          <div
            key={item.provider}
            style={{ border: '1px solid #e2e8f0', borderRadius: 'var(--radius-md)', padding: 'var(--space-3)' }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 'var(--space-2)' }}>
              <span style={{ fontSize: 13, fontWeight: 600 }}>{API_KEY_PROVIDER_LABELS[item.provider] ?? item.provider}</span>
              <span className={`krds-badge small ${item.registered ? 'bg-primary' : 'bg-secondary'}`}>
                {item.registered ? '등록됨' : '미등록'}
              </span>
            </div>

            <div style={{ display: 'flex', flexDirection: 'row', flexWrap: 'wrap', gap: 'var(--space-2)' }}>
              <input
                type="password"
                value={drafts[item.provider] || ''}
                onChange={(e) => setDrafts((d) => ({ ...d, [item.provider]: e.target.value }))}
                placeholder={item.registered ? '새 API 키로 교체...' : 'API 키 입력...'}
                className="krds-input small"
                style={{ flex: '1 1 220px' }}
              />
              <button
                type="button"
                onClick={() => handleSave(item.provider)}
                disabled={setApiKey.isPending || !(drafts[item.provider] || '').trim()}
                className="krds-btn small primary"
              >
                {savedProvider === item.provider ? <Check size={14} /> : null}
                저장
              </button>
              {item.registered && (
                <button
                  type="button"
                  onClick={() => deleteApiKey.mutate({ projectId, provider: item.provider })}
                  disabled={deleteApiKey.isPending}
                  className="krds-btn small text"
                  style={{ color: '#dc2626' }}
                >
                  <Trash2 size={14} />
                  삭제
                </button>
              )}
            </div>
            {item.updated_at && (
              <p style={{ fontSize: 12, color: 'var(--color-text-muted)', margin: 'var(--space-2) 0 0' }}>
                마지막 업데이트: {new Date(item.updated_at).toLocaleString('ko-KR')}
              </p>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
