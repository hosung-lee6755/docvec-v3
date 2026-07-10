import { useState, useEffect } from 'react'
import { KeyRound, Trash2, Check, User as UserIcon, Lock, Bot, RotateCcw } from 'lucide-react'
import { useApiKeys, useSetApiKey, useDeleteApiKey } from '../hooks/useApiKeys'
import { useProfile, useUpdateProfile, useChangePassword, useSetSystemPrompt } from '../hooks/useProfile'
import { useChatModels } from '../hooks/useChat'
import { useAuthStore } from '../store/authStore'

const PROVIDER_LABELS: Record<string, string> = {
  openai: 'OpenAI',
  anthropic: 'Anthropic',
}

const ROLE_LABELS: Record<string, string> = {
  admin: '관리자',
  editor: '편집자',
  viewer: '조회자',
}

function SectionCard({ title, icon, children }: { title: string; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <div style={{
      background: '#fff', border: '1px solid #e2e8f0',
      borderRadius: 'var(--radius-md)', padding: 'var(--space-4)',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', marginBottom: 'var(--space-3)' }}>
        {icon}
        <span style={{ fontWeight: 600 }}>{title}</span>
      </div>
      {children}
    </div>
  )
}

function ProfileSection() {
  const { data: profile, isLoading } = useProfile()
  const updateProfile = useUpdateProfile()
  const updateAuthUser = useAuthStore((s) => s.updateUser)
  const [username, setUsername] = useState('')
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    if (profile) setUsername(profile.username)
  }, [profile])

  const handleSave = () => {
    const trimmed = username.trim()
    if (!trimmed || trimmed === profile?.username) return
    updateProfile.mutate(trimmed, {
      onSuccess: (data) => {
        updateAuthUser({ username: data.username })
        setSaved(true)
        setTimeout(() => setSaved(false), 2000)
      },
    })
  }

  if (isLoading || !profile) {
    return <div className="krds-spinner" role="status"><span className="sr-only">로딩 중</span></div>
  }

  return (
    <SectionCard title="프로필" icon={<UserIcon size={16} />}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
        <div>
          <p style={{ fontSize: 12, color: 'var(--color-text-muted)', margin: '0 0 4px' }}>이메일</p>
          <p style={{ margin: 0, fontSize: 14 }}>{profile.email}</p>
        </div>

        <div>
          <p style={{ fontSize: 12, color: 'var(--color-text-muted)', margin: '0 0 4px' }}>이름</p>
          <div style={{ display: 'flex', flexDirection: 'row', flexWrap: 'wrap', gap: 'var(--space-2)' }}>
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="krds-input small"
              style={{ flex: '1 1 260px' }}
            />
            <button
              type="button"
              onClick={handleSave}
              disabled={updateProfile.isPending || !username.trim() || username.trim() === profile.username}
              className="krds-btn small primary"
            >
              {saved ? <Check size={14} /> : null}
              저장
            </button>
          </div>
        </div>

        <div style={{ display: 'flex', gap: 'var(--space-6)' }}>
          <div>
            <p style={{ fontSize: 12, color: 'var(--color-text-muted)', margin: '0 0 4px' }}>역할</p>
            <p style={{ margin: 0, fontSize: 14 }}>{ROLE_LABELS[profile.role] ?? profile.role}</p>
          </div>
          <div>
            <p style={{ fontSize: 12, color: 'var(--color-text-muted)', margin: '0 0 4px' }}>가입일</p>
            <p style={{ margin: 0, fontSize: 14 }}>{new Date(profile.created_at).toLocaleDateString('ko-KR')}</p>
          </div>
        </div>
      </div>
    </SectionCard>
  )
}

function PasswordSection() {
  const changePassword = useChangePassword()
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [saved, setSaved] = useState(false)

  const mismatch = confirmPassword.length > 0 && newPassword !== confirmPassword
  const tooShort = newPassword.length > 0 && newPassword.length < 8
  const canSubmit = currentPassword && newPassword && confirmPassword && !mismatch && !tooShort

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!canSubmit) return
    changePassword.mutate(
      { currentPassword, newPassword },
      {
        onSuccess: () => {
          setCurrentPassword('')
          setNewPassword('')
          setConfirmPassword('')
          setSaved(true)
          setTimeout(() => setSaved(false), 2000)
        },
      }
    )
  }

  return (
    <SectionCard title="비밀번호 변경" icon={<Lock size={16} />}>
      <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)', maxWidth: 320 }}>
        <input
          type="password"
          value={currentPassword}
          onChange={(e) => setCurrentPassword(e.target.value)}
          placeholder="현재 비밀번호"
          className="krds-input small"
        />
        <input
          type="password"
          value={newPassword}
          onChange={(e) => setNewPassword(e.target.value)}
          placeholder="새 비밀번호 (8자 이상)"
          className="krds-input small"
        />
        <input
          type="password"
          value={confirmPassword}
          onChange={(e) => setConfirmPassword(e.target.value)}
          placeholder="새 비밀번호 확인"
          className="krds-input small"
        />
        {mismatch && (
          <p style={{ fontSize: 12, color: '#dc2626', margin: 0 }}>새 비밀번호가 일치하지 않습니다.</p>
        )}
        {changePassword.isError && (
          <p style={{ fontSize: 12, color: '#dc2626', margin: 0 }}>현재 비밀번호가 일치하지 않습니다.</p>
        )}
        <button
          type="submit"
          disabled={!canSubmit || changePassword.isPending}
          className="krds-btn small primary"
          style={{ alignSelf: 'flex-start' }}
        >
          {saved ? <Check size={14} /> : null}
          변경
        </button>
      </form>
    </SectionCard>
  )
}

function SystemPromptSection() {
  const { data: profile, isLoading: profileLoading } = useProfile()
  const { data: modelsData } = useChatModels()
  const setSystemPrompt = useSetSystemPrompt()
  const [value, setValue] = useState('')
  const [initialized, setInitialized] = useState(false)
  const [saved, setSaved] = useState(false)

  const defaultPrompt = modelsData?.default_system_prompt ?? ''

  useEffect(() => {
    if (profile && !initialized) {
      setValue(profile.system_prompt ?? defaultPrompt)
      setInitialized(true)
    }
  }, [profile, defaultPrompt, initialized])

  const handleSave = () => {
    setSystemPrompt.mutate(value.trim(), {
      onSuccess: () => {
        setSaved(true)
        setTimeout(() => setSaved(false), 2000)
      },
    })
  }

  const handleReset = () => {
    setValue(defaultPrompt)
    setSystemPrompt.mutate(null)
  }

  if (profileLoading || !profile) {
    return <div className="krds-spinner" role="status"><span className="sr-only">로딩 중</span></div>
  }

  return (
    <SectionCard title="시스템 프롬프트" icon={<Bot size={16} />}>
      <p style={{ fontSize: 13, color: 'var(--color-text-muted)', margin: '0 0 var(--space-3)' }}>
        AI 답변 생성 시 사용할 지침을 직접 지정할 수 있습니다. 비워두면 기본 지침이 사용됩니다.
      </p>
      <textarea
        value={value}
        onChange={(e) => setValue(e.target.value)}
        rows={14}
        className="krds-input small"
        style={{ width: '100%', resize: 'vertical', fontFamily: 'inherit', lineHeight: 1.5 }}
      />
      <div style={{ display: 'flex', gap: 'var(--space-2)', marginTop: 'var(--space-2)' }}>
        <button
          type="button"
          onClick={handleSave}
          disabled={setSystemPrompt.isPending || !value.trim()}
          className="krds-btn small primary"
        >
          {saved ? <Check size={14} /> : null}
          저장
        </button>
        {!!profile.system_prompt && (
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
    </SectionCard>
  )
}

function ApiKeySection() {
  const { data, isLoading } = useApiKeys()
  const setApiKey = useSetApiKey()
  const deleteApiKey = useDeleteApiKey()
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [savedProvider, setSavedProvider] = useState<string | null>(null)

  const handleSave = (provider: string) => {
    const apiKey = (drafts[provider] || '').trim()
    if (!apiKey) return
    setApiKey.mutate(
      { provider, apiKey },
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
    <SectionCard title="AI 답변 API 키" icon={<KeyRound size={16} />}>
      <p style={{ fontSize: 13, color: 'var(--color-text-muted)', margin: '0 0 var(--space-4)' }}>
        AI 답변 기능에서 사용할 OpenAI / Anthropic API 키를 등록합니다. 키는 암호화되어 저장되며,
        본인 계정의 답변 생성 요청에만 사용됩니다. 로컬 모델(Qwen)은 키 등록 없이 바로 사용할 수
        있습니다.
      </p>

      {isLoading && <div className="krds-spinner" role="status"><span className="sr-only">로딩 중</span></div>}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
        {data?.items.map((item) => (
          <div
            key={item.provider}
            style={{
              border: '1px solid #e2e8f0',
              borderRadius: 'var(--radius-md)', padding: 'var(--space-3)',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 'var(--space-2)' }}>
              <span style={{ fontSize: 13, fontWeight: 600 }}>{PROVIDER_LABELS[item.provider] ?? item.provider}</span>
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
                  onClick={() => deleteApiKey.mutate(item.provider)}
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
    </SectionCard>
  )
}

type SettingsTab = 'ai' | 'account'

const TABS: { key: SettingsTab; label: string }[] = [
  { key: 'account', label: '계정관리' },
  { key: 'ai', label: 'AI 관리' },
]

export default function SettingsPage() {
  const [tab, setTab] = useState<SettingsTab>('account')

  return (
    <div>
      <h1 style={{ fontSize: 24, fontWeight: 700, marginBottom: 'var(--space-6)' }}>설정</h1>

      <div style={{ display: 'flex', gap: 'var(--space-8)', alignItems: 'flex-start' }}>
        <nav style={{ width: 180, flexShrink: 0, display: 'flex', flexDirection: 'column', gap: 2 }}>
          {TABS.map((t) => (
            <button
              key={t.key}
              type="button"
              onClick={() => setTab(t.key)}
              style={{
                background: tab === t.key ? '#eff6ff' : 'transparent',
                border: 'none',
                cursor: 'pointer',
                textAlign: 'left',
                borderRadius: 'var(--radius-md, 8px)',
                padding: '10px 12px',
                fontSize: 14,
                color: tab === t.key ? '#1d4ed8' : '#475569',
                fontWeight: tab === t.key ? 600 : 500,
              }}
            >
              {t.label}
            </button>
          ))}
        </nav>

        <div style={{ flex: '1 1 auto', maxWidth: 640, display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
          {tab === 'ai' && (
            <>
              <SystemPromptSection />
              <ApiKeySection />
            </>
          )}
          {tab === 'account' && (
            <>
              <ProfileSection />
              <PasswordSection />
            </>
          )}
        </div>
      </div>
    </div>
  )
}
