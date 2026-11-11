import { useState } from 'react'
import { Check, Copy, Plug, Trash2 } from 'lucide-react'
import {
  TOKEN_STATUS_BADGE, TOKEN_STATUS_LABELS, mcpConnectCommand,
  useCreateAccessToken, useMyAccessTokens, useRevokeMyAccessToken,
} from '../../hooks/useAccessTokens'
import type { IssuedToken } from '../../hooks/useAccessTokens'
import { errorMessage, formatDateTime } from '../connectors/connectorLabels'

// v3 마일스톤 4 — 내 개인 접근 토큰. 이 토큰을 넣은 에이전트는 나와 같은 문서만 볼 수 있다.

const CARD: React.CSSProperties = {
  background: '#fff', border: '1px solid #e2e8f0', borderRadius: 'var(--radius-md)', padding: 'var(--space-4)',
}
const MUTED: React.CSSProperties = { fontSize: 13, color: 'var(--color-text-muted)' }
const CODE: React.CSSProperties = {
  display: 'block', fontFamily: 'var(--font-mono, monospace)', fontSize: 12, background: '#f8fafc',
  border: '1px solid #e2e8f0', borderRadius: 4, padding: 'var(--space-2)', wordBreak: 'break-all',
}
const ERROR: React.CSSProperties = { color: '#dc2626', fontSize: 13, margin: 'var(--space-2) 0 0' }

function CopyButton({ text, label }: { text: string; label: string }) {
  const [isCopied, setIsCopied] = useState(false)
  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text)
      setIsCopied(true)
      setTimeout(() => setIsCopied(false), 2000)
    } catch {
      // 클립보드를 쓸 수 없는 환경(HTTP 등)에서는 사용자가 직접 선택해 복사한다
      setIsCopied(false)
    }
  }
  return (
    <button type="button" className="krds-btn xsmall secondary" onClick={handleCopy} aria-label={label}>
      {isCopied ? <Check size={12} /> : <Copy size={12} />} {isCopied ? '복사됨' : '복사'}
    </button>
  )
}

function IssuedTokenNotice({ issued, path, onClose }: { issued: IssuedToken; path: string; onClose: () => void }) {
  const command = mcpConnectCommand(window.location.origin, path, issued.token)
  return (
    <div role="alert" style={{ border: '1px solid #fcd34d', background: '#fffbeb', borderRadius: 'var(--radius-md)', padding: 'var(--space-3)', display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
      <strong style={{ fontSize: 13 }}>토큰을 지금 복사해 두세요. 이 창을 닫으면 다시 볼 수 없습니다.</strong>
      <span style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'center' }}>
        <code style={{ ...CODE, flex: 1 }} aria-label="발급된 토큰">{issued.token}</code>
        <CopyButton text={issued.token} label="토큰 복사" />
      </span>
      <span style={MUTED}>Claude Code에서는 아래 명령으로 연결합니다.</span>
      <span style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'center' }}>
        <code style={{ ...CODE, flex: 1 }}>{command}</code>
        <CopyButton text={command} label="연결 명령 복사" />
      </span>
      <span>
        <button type="button" className="krds-btn xsmall text" onClick={onClose}>복사했습니다. 닫기</button>
      </span>
    </div>
  )
}

export default function AccessTokenSection() {
  const { data, isLoading, isError } = useMyAccessTokens()
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
    <section style={CARD} aria-labelledby="access-token-heading">
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', marginBottom: 'var(--space-3)' }}>
        <Plug size={16} />
        <h2 id="access-token-heading" style={{ fontWeight: 600, fontSize: 16, margin: 0 }}>외부 에이전트 연결 토큰</h2>
      </div>
      <p style={{ ...MUTED, margin: '0 0 var(--space-3)' }}>
        Claude Code 같은 AI 에이전트가 사내 문서를 검색하도록 연결할 때 씁니다. 에이전트는 이 토큰을 만든 사람과
        같은 권한으로만 문서를 보며, 에이전트가 한 모든 조회는 감사 로그에 남습니다.
      </p>

      {isLoading && <div className="krds-spinner" role="status"><span className="sr-only">로딩 중</span></div>}
      {isError && <p style={ERROR}>토큰 목록을 불러오지 못했습니다.</p>}
      {data && !data.mcp_enabled && (
        <p style={{ ...MUTED, background: '#f8fafc', padding: 'var(--space-2)', borderRadius: 4 }}>
          관리자가 외부 에이전트 연결을 켜지 않아 지금은 새 토큰을 만들 수 없습니다.
        </p>
      )}

      {issued && data && <IssuedTokenNotice issued={issued} path={data.mcp_path} onClose={() => setIssued(null)} />}

      {data?.mcp_enabled && !issued && (
        <form onSubmit={handleCreate} aria-label="새 토큰 만들기" style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--space-2)', alignItems: 'flex-end' }}>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 13, flex: '1 1 200px' }}>
            이름
            <input className="krds-input small" value={name} maxLength={100} placeholder="예: 내 노트북의 Claude Code"
              onChange={(e) => setName(e.target.value)} />
          </label>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 13, width: 120 }}>
            유효 기간(일)
            <input className="krds-input small" type="number" min={1} max={maxDays} value={effectiveDays}
              onChange={(e) => setDays(Number(e.target.value))} />
          </label>
          <button type="submit" className="krds-btn small primary" disabled={!canCreate}>토큰 만들기</button>
        </form>
      )}
      {create.isError && <p style={ERROR}>{errorMessage(create.error, '토큰을 만들지 못했습니다.')}</p>}

      {data && data.items.length > 0 && (
        <ul aria-label="내 토큰 목록" style={{ listStyle: 'none', padding: 0, margin: 'var(--space-4) 0 0', display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
          {data.items.map((t) => (
            <li key={t.id} style={{ border: '1px solid #e2e8f0', borderRadius: 'var(--radius-md)', padding: 'var(--space-2) var(--space-3)', display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
              <span style={{ flex: 1, minWidth: 0 }}>
                <span style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 14, fontWeight: 600 }}>
                  {t.name}
                  <span className={`krds-badge xsmall ${TOKEN_STATUS_BADGE[t.status]}`}>{TOKEN_STATUS_LABELS[t.status]}</span>
                </span>
                <span style={{ display: 'block', fontSize: 12, color: 'var(--color-text-muted)' }}>
                  {t.token_prefix}… · 만료 {formatDateTime(t.expires_at)} · 마지막 사용 {formatDateTime(t.last_used_at)}
                </span>
              </span>
              {t.status === 'active' && (
                <button type="button" className="krds-btn xsmall text" style={{ color: '#dc2626' }}
                  disabled={revoke.isPending} onClick={() => handleRevoke(t.id, t.name)} aria-label={`${t.name} 회수`}>
                  <Trash2 size={12} /> 회수
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {revoke.isError && <p style={ERROR}>{errorMessage(revoke.error, '토큰을 회수하지 못했습니다.')}</p>}
    </section>
  )
}
