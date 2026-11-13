import { useState } from 'react'
import { Plug, Trash2 } from 'lucide-react'
import {
  TOKEN_STATUS_BADGE, TOKEN_STATUS_LABELS, mcpConnectCommand,
  useCreateAccessToken, useMyAccessTokens, useRevokeMyAccessToken,
} from '../../hooks/useAccessTokens'
import type { IssuedToken } from '../../hooks/useAccessTokens'
import { formatDateTime } from '../connectors/connectorLabels'
import AccessTokenGuide, { CopyButton } from './AccessTokenGuide'
import { Alert, Badge, Button, Card, ErrorAlert, Field, Input, toneFromKrdsClass } from '../ui'
import '../../styles/screens/user.css'

// v3 마일스톤 4 — 내 개인 접근 토큰. 이 토큰을 넣은 에이전트는 나와 같은 문서만 볼 수 있다.

function IssuedTokenNotice({ issued, path, onClose }: { issued: IssuedToken; path: string; onClose: () => void }) {
  const command = mcpConnectCommand(window.location.origin, path, issued.token)
  return (
    <Alert tone="warning">
      <div className="user-token__notice">
        <strong className="user-token__notice-title">토큰을 지금 복사해 두세요. 이 창을 닫으면 다시 볼 수 없습니다.</strong>
        <span className="user-token__row">
          <code className="user-token__code" aria-label="발급된 토큰">{issued.token}</code>
          <CopyButton text={issued.token} label="토큰 복사" />
        </span>
        <span className="user-token__muted">Claude Code에서는 아래 명령으로 연결합니다.</span>
        <span className="user-token__row">
          <code className="user-token__code">{command}</code>
          <CopyButton text={command} label="연결 명령 복사" />
        </span>
        <span>
          <Button variant="ghost" size="sm" onClick={onClose}>복사했습니다. 닫기</Button>
        </span>
      </div>
    </Alert>
  )
}

export default function AccessTokenSection() {
  const { data, isLoading, isError, error, refetch } = useMyAccessTokens()
  const create = useCreateAccessToken()
  const revoke = useRevokeMyAccessToken()
  const [name, setName] = useState('')
  const [days, setDays] = useState<number | null>(null)
  const [issued, setIssued] = useState<IssuedToken | null>(null)

  const maxDays = data?.max_days ?? 365
  const effectiveDays = days ?? data?.default_days ?? 90
  const isValidDays = Number.isInteger(effectiveDays) && effectiveDays >= 1 && effectiveDays <= maxDays
  const canCreate = !!data?.mcp_enabled && !!name.trim() && isValidDays && !create.isPending

  const handleCreate = (e: React.FormEvent) => {
    e.preventDefault()
    if (!canCreate) return
    create.mutate(
      { name: name.trim(), expires_in_days: effectiveDays },
      { onSuccess: (token) => { setIssued(token); setName(''); setDays(null) } },
    )
  }

  const handleRevoke = (id: string, tokenName: string) => {
    if (!window.confirm(`"${tokenName}" 토큰을 회수할까요? 이 토큰을 쓰는 에이전트는 바로 연결이 끊깁니다.`)) return
    revoke.mutate(id)
  }

  return (
    <Card title={<span className="user-settings__card-title"><Plug size={16} aria-hidden="true" />외부 에이전트 연결 토큰</span>}>
      <div className="user-settings__stack">
      <p className="user-token__muted user-token__intro">
        Claude Code 같은 AI 에이전트가 사내 문서를 검색하도록 연결할 때 씁니다. 에이전트는 이 토큰을 만든 사람과
        같은 권한으로만 문서를 보며, 에이전트가 한 모든 조회는 감사 로그에 남습니다.
      </p>

      {data && <AccessTokenGuide mcpPath={data.mcp_path} isOpenByDefault={data.items.length === 0} />}

      {isLoading && <div className="user-spinner" role="status"><span className="sr-only">로딩 중</span></div>}
      {isError && <ErrorAlert error={error} message="토큰 목록을 불러오지 못했습니다." onRetry={() => refetch()} />}
      {data && !data.mcp_enabled && (
        <p className="user-token__notice-box">
          관리자가 외부 에이전트 연결을 켜지 않아 지금은 새 토큰을 만들 수 없습니다.
        </p>
      )}

      {issued && data && <IssuedTokenNotice issued={issued} path={data.mcp_path} onClose={() => setIssued(null)} />}

      {data?.mcp_enabled && !issued && (
        <form onSubmit={handleCreate} aria-label="새 토큰 만들기" className="user-token__form">
          <div className="user-token__field-name">
            <Field label="이름">
              {(id) => (
                <Input id={id} controlSize="sm" value={name} maxLength={100} placeholder="예: 내 노트북의 Claude Code"
                  onChange={(e) => setName(e.target.value)} />
              )}
            </Field>
          </div>
          <div className="user-token__field-days">
            <Field label="유효 기간(일)">
              {(id) => (
                <Input id={id} controlSize="sm" type="number" min={1} max={maxDays} value={effectiveDays}
                  onChange={(e) => setDays(Number(e.target.value))} />
              )}
            </Field>
          </div>
          <Button type="submit" variant="primary" size="sm" disabled={!canCreate}>토큰 만들기</Button>
        </form>
      )}
      {create.isError && <ErrorAlert error={create.error} message="토큰을 만들지 못했습니다." />}

      {data && data.items.length > 0 && (
        <ul aria-label="내 토큰 목록" className="user-token__list">
          {data.items.map((t) => (
            <li key={t.id} className="user-token__item">
              <span className="user-token__item-main">
                <span className="user-token__item-name">
                  {t.name}
                  <Badge tone={toneFromKrdsClass(TOKEN_STATUS_BADGE[t.status])} hasDot>{TOKEN_STATUS_LABELS[t.status]}</Badge>
                </span>
                <span className="user-token__muted user-token__item-meta">
                  {t.token_prefix}… · 만료 {formatDateTime(t.expires_at)} · 마지막 사용 {formatDateTime(t.last_used_at)}
                </span>
              </span>
              {t.status === 'active' && (
                <Button variant="danger" size="sm" disabled={revoke.isPending}
                  onClick={() => handleRevoke(t.id, t.name)} aria-label={`${t.name} 회수`}
                  icon={<Trash2 size={12} />}>
                  회수
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
      {revoke.isError && <ErrorAlert error={revoke.error} message="토큰을 회수하지 못했습니다." />}
      </div>
    </Card>
  )
}
