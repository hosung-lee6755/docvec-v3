import { useState, useEffect } from 'react'
import { KeyRound, Trash2, Check, User as UserIcon, Lock, Bot, RotateCcw } from 'lucide-react'
import { useApiKeys, useSetApiKey, useDeleteApiKey } from '../hooks/useApiKeys'
import { useProfile, useUpdateProfile, useChangePassword, useSetSystemPrompt } from '../hooks/useProfile'
import { useChatModels } from '../hooks/useChat'
import { useAuthStore } from '../store/authStore'
import AccessTokenSection from '../components/settings/AccessTokenSection'
import { ROLE_LABELS } from '../lib/roleLabels'
import { Alert, Badge, Button, Card, DescriptionList, ErrorAlert, Field, Input, Page, PageBody, PageHeader, Textarea } from '../components/ui'
import '../styles/screens/user.css'

const PROVIDER_LABELS: Record<string, string> = {
  openai: 'OpenAI',
  anthropic: 'Anthropic',
}


function SectionCard({ title, icon, children }: { title: string; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <Card title={<span className="user-settings__card-title">{icon}{title}</span>}>
      {children}
    </Card>
  )
}

function Loading() {
  return <div className="user-spinner" role="status"><span className="sr-only">로딩 중</span></div>
}

function ProfileSection() {
  const { data: profile, isLoading, isError, error, refetch } = useProfile()
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

  if (isError) {
    return <ErrorAlert error={error} message="프로필을 불러오지 못했습니다." onRetry={() => refetch()} />
  }
  if (isLoading || !profile) {
    return <Loading />
  }

  return (
    <SectionCard title="프로필" icon={<UserIcon size={16} />}>
      <div className="user-settings__stack">
        <DescriptionList items={[
          { key: 'email', term: '이메일', detail: profile.email },
          { key: 'role', term: '역할', detail: ROLE_LABELS[profile.role] ?? profile.role },
          { key: 'created', term: '가입일', detail: new Date(profile.created_at).toLocaleDateString('ko-KR') },
        ]} />

        <div className="user-settings__row">
          <div className="user-settings__grow">
            <Field label="이름">
              {(id) => (
                <Input id={id} controlSize="sm" value={username} onChange={(e) => setUsername(e.target.value)} />
              )}
            </Field>
          </div>
          <Button
            variant="primary"
            size="sm"
            onClick={handleSave}
            disabled={updateProfile.isPending || !username.trim() || username.trim() === profile.username}
            icon={saved ? <Check size={14} /> : undefined}
          >
            저장
          </Button>
        </div>
        {updateProfile.isError && <ErrorAlert error={updateProfile.error} message="이름을 저장하지 못했습니다." />}
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
      <form onSubmit={handleSubmit} className="user-settings__stack user-settings__stack--narrow">
        <Input
          type="password"
          controlSize="sm"
          value={currentPassword}
          onChange={(e) => setCurrentPassword(e.target.value)}
          placeholder="현재 비밀번호"
          aria-label="현재 비밀번호"
        />
        <Input
          type="password"
          controlSize="sm"
          value={newPassword}
          onChange={(e) => setNewPassword(e.target.value)}
          placeholder="새 비밀번호 (8자 이상)"
          aria-label="새 비밀번호"
        />
        <Input
          type="password"
          controlSize="sm"
          value={confirmPassword}
          onChange={(e) => setConfirmPassword(e.target.value)}
          placeholder="새 비밀번호 확인"
          aria-label="새 비밀번호 확인"
        />
        {mismatch && <Alert tone="danger">새 비밀번호가 일치하지 않습니다.</Alert>}
        {changePassword.isError && <ErrorAlert error={changePassword.error} message="비밀번호를 바꾸지 못했습니다." />}
        <Button
          type="submit"
          variant="primary"
          size="sm"
          disabled={!canSubmit || changePassword.isPending}
          className="user-settings__submit"
          icon={saved ? <Check size={14} /> : undefined}
        >
          변경
        </Button>
      </form>
    </SectionCard>
  )
}

function SystemPromptSection() {
  const { data: profile, isLoading: profileLoading, isError: isProfileError, error: profileError, refetch } = useProfile()
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

  if (isProfileError) {
    return <ErrorAlert error={profileError} message="시스템 프롬프트를 불러오지 못했습니다." onRetry={() => refetch()} />
  }
  if (profileLoading || !profile) {
    return <Loading />
  }

  return (
    <SectionCard title="시스템 프롬프트" icon={<Bot size={16} />}>
      <p className="user-settings__muted">
        AI 답변 생성 시 사용할 지침을 직접 지정할 수 있습니다. 비워두면 기본 지침이 사용됩니다.
      </p>
      <Field label="지침 내용">
        {(id) => (
          <Textarea
            id={id}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            rows={14}
            className="user-settings__prompt"
          />
        )}
      </Field>
      <div className="user-settings__actions">
        <Button
          variant="primary"
          size="sm"
          onClick={handleSave}
          disabled={setSystemPrompt.isPending || !value.trim()}
          icon={saved ? <Check size={14} /> : undefined}
        >
          저장
        </Button>
        {!!profile.system_prompt && (
          <Button
            variant="ghost"
            size="sm"
            onClick={handleReset}
            disabled={setSystemPrompt.isPending}
            icon={<RotateCcw size={14} />}
          >
            기본값으로 초기화
          </Button>
        )}
      </div>
      {setSystemPrompt.isError && <ErrorAlert error={setSystemPrompt.error} message="시스템 프롬프트를 저장하지 못했습니다." />}
    </SectionCard>
  )
}

function ApiKeySection() {
  const { data, isLoading, isError, error, refetch } = useApiKeys()
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
      <p className="user-settings__muted user-settings__intro">
        AI 답변 기능에서 사용할 OpenAI / Anthropic API 키를 등록합니다. 키는 암호화되어 저장되며,
        본인 계정의 답변 생성 요청에만 사용됩니다. 로컬 모델(Qwen)은 키 등록 없이 바로 사용할 수
        있습니다.
      </p>

      {isLoading && <Loading />}
      {isError && <ErrorAlert error={error} message="API 키 목록을 불러오지 못했습니다." onRetry={() => refetch()} />}
      {setApiKey.isError && <ErrorAlert error={setApiKey.error} message="API 키를 저장하지 못했습니다." />}
      {deleteApiKey.isError && <ErrorAlert error={deleteApiKey.error} message="API 키를 삭제하지 못했습니다." />}

      <div className="user-settings__stack">
        {data?.items.map((item) => (
          <div key={item.provider} className="user-settings__key">
            <div className="user-settings__key-head">
              <span className="user-settings__key-name">{PROVIDER_LABELS[item.provider] ?? item.provider}</span>
              <Badge tone={item.registered ? 'info' : 'neutral'} hasDot>
                {item.registered ? '등록됨' : '미등록'}
              </Badge>
            </div>

            <div className="user-settings__row">
              <Field label={`${PROVIDER_LABELS[item.provider] ?? item.provider} API 키`}>
                {(id) => (
                  <Input
                    id={id}
                    type="password"
                    controlSize="sm"
                    value={drafts[item.provider] || ''}
                    onChange={(e) => setDrafts((d) => ({ ...d, [item.provider]: e.target.value }))}
                    placeholder={item.registered ? '새 API 키로 교체...' : 'API 키 입력...'}
                  />
                )}
              </Field>
              <Button
                variant="primary"
                size="sm"
                onClick={() => handleSave(item.provider)}
                disabled={setApiKey.isPending || !(drafts[item.provider] || '').trim()}
                icon={savedProvider === item.provider ? <Check size={14} /> : undefined}
              >
                저장
              </Button>
              {item.registered && (
                <Button
                  variant="danger"
                  size="sm"
                  onClick={() => deleteApiKey.mutate(item.provider)}
                  disabled={deleteApiKey.isPending}
                  icon={<Trash2 size={14} />}
                >
                  삭제
                </Button>
              )}
            </div>
            {item.updated_at && (
              <p className="user-settings__muted user-settings__updated">
                마지막 업데이트: {new Date(item.updated_at).toLocaleString('ko-KR')}
              </p>
            )}
          </div>
        ))}
      </div>
    </SectionCard>
  )
}

type SettingsTab = 'ai' | 'account' | 'agent'

const TABS: { key: SettingsTab; label: string }[] = [
  { key: 'account', label: '계정 관리' },
  { key: 'ai', label: 'AI 관리' },
  { key: 'agent', label: '외부 에이전트' },
]

export default function SettingsPage() {
  const [tab, setTab] = useState<SettingsTab>('account')

  return (
    <Page>
      <PageHeader title="설정" />

      <PageBody>
        <div className="user-settings">
          <nav className="user-settings__nav" aria-label="설정 메뉴">
            {TABS.map((t) => (
              <button
                key={t.key}
                type="button"
                onClick={() => setTab(t.key)}
                aria-current={tab === t.key ? 'page' : undefined}
                className={`user-settings__nav-item${tab === t.key ? ' is-active' : ''}`}
              >
                {t.label}
              </button>
            ))}
          </nav>

          <div className="user-settings__content">
            {tab === 'ai' && (
              <>
                <SystemPromptSection />
                <ApiKeySection />
              </>
            )}
            {tab === 'agent' && <AccessTokenSection />}
            {tab === 'account' && (
              <>
                <ProfileSection />
                <PasswordSection />
              </>
            )}
          </div>
        </div>
      </PageBody>
    </Page>
  )
}
