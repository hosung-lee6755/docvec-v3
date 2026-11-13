import { useState, type CSSProperties } from 'react'
import {
  useArchiveDocument, useCompareVersions, useDocumentVersions, useRestoreVersion, useSetDocumentExpiry,
  type DocumentVersion,
} from '../../hooks/useDocumentLifecycle'
import { STATUS_LABELS } from '../../lib/documentStatus'
import { LIFECYCLE_STATE_LABELS, endOfLocalDayIso, formatLocalDate } from '../../lib/documentLifecycle'
import { apiErrorDetail } from '../../lib/apiError'

// 같은 문서의 버전 이력과 수명주기 조작. 검색에는 현재 버전만 쓰이고, 이전 버전과 보관 문서는
// 여기서 되돌리거나 두 버전의 본문을 비교할 수 있다.

interface VersionHistoryPanelProps {
  documentId: string
}

const DIFF_ADDED_COLOR = 'var(--color-success)'
const DIFF_REMOVED_COLOR = 'var(--color-danger)'

function diffLineStyle(line: string): CSSProperties {
  const isAdded = line.startsWith('+') && !line.startsWith('+++')
  const isRemoved = line.startsWith('-') && !line.startsWith('---')
  if (isAdded) return { color: DIFF_ADDED_COLOR, background: 'var(--color-success-bg)' }
  if (isRemoved) return { color: DIFF_REMOVED_COLOR, background: 'var(--color-danger-bg)' }
  if (line.startsWith('@@')) return { color: 'var(--color-text-muted)' }
  return {}
}

function canRestore(version: DocumentVersion): boolean {
  return (version.lifecycle_state === 'superseded' || version.lifecycle_state === 'archived') && version.status === 'INDEXED'
}

function ErrorText({ message }: { message: string | null }) {
  if (!message) return null
  return <p role="alert" style={{ fontSize: 12, color: 'var(--color-danger)', margin: 0 }}>{message}</p>
}

function VersionDiff({ baseId, currentId }: { baseId: string; currentId: string }) {
  const compare = useCompareVersions(baseId, currentId)
  if (compare.isLoading) return <p style={{ fontSize: 12, color: 'var(--color-text-muted)', margin: 0 }}>비교 중...</p>
  if (compare.isError) {
    return <ErrorText message={apiErrorDetail(compare.error, '두 버전을 비교하지 못했습니다.')} />
  }
  if (!compare.data) return null
  const { base_version, target_version, added_lines, removed_lines, diff, truncated } = compare.data
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
      <p style={{ fontSize: 12, color: 'var(--color-text-muted)', margin: 0 }}>
        {base_version}번 버전 → {target_version}번 버전 · 추가 {added_lines}줄 · 삭제 {removed_lines}줄
        {truncated && ' · 변경이 많아 앞부분만 보여줍니다.'}
      </p>
      {diff.length === 0 ? (
        <p style={{ fontSize: 12, color: 'var(--color-text-muted)', margin: 0 }}>두 버전의 본문이 같습니다.</p>
      ) : (
        <pre style={{ fontSize: 12, maxHeight: 280, overflow: 'auto', margin: 0, padding: 'var(--space-2)', background: 'var(--color-surface-subtle)', borderRadius: 'var(--radius-sm)', whiteSpace: 'pre-wrap' }}>
          {diff.map((line, index) => (
            <span key={index} style={{ display: 'block', ...diffLineStyle(line) }}>{line || ' '}</span>
          ))}
        </pre>
      )}
    </div>
  )
}

export default function VersionHistoryPanel({ documentId }: VersionHistoryPanelProps) {
  const versions = useDocumentVersions(documentId)
  const archive = useArchiveDocument()
  const restore = useRestoreVersion()
  const setExpiry = useSetDocumentExpiry()
  const [compareId, setCompareId] = useState<string | null>(null)
  // null이면 서버의 만료일을 그대로 보여준다. 사용자가 고치기 시작하면 입력값을 따로 든다.
  const [expiryDraft, setExpiryDraft] = useState<string | null>(null)

  if (versions.isLoading) return null
  if (versions.isError) {
    return (
      <section aria-label="문서 버전 이력">
        <h3 style={{ fontSize: 14, margin: '0 0 var(--space-1)' }}>문서 버전</h3>
        <ErrorText message={apiErrorDetail(versions.error, '버전 이력을 불러오지 못했습니다.')} />
      </section>
    )
  }

  const items = versions.data?.items ?? []
  const current = items.find((v) => v.lifecycle_state === 'current') ?? null
  const pageItem = items.find((v) => v.id === documentId) ?? null
  const serverExpiry = pageItem?.expires_at ? formatLocalDate(pageItem.expires_at) : ''
  const expiryValue = expiryDraft ?? serverExpiry
  const compareBaseId = compareId && current && compareId !== current.id ? compareId : null

  const handleRestore = (version: DocumentVersion) => {
    const message = `${version.version_number}번 버전을 현재 버전으로 되돌릴까요? 지금의 현재 버전은 이전 버전이 되어 검색에서 빠집니다.`
    if (window.confirm(message)) restore.mutate(version.id)
  }

  const handleArchive = (version: DocumentVersion) => {
    if (window.confirm('이 문서를 보관할까요? 보관된 문서는 검색과 답변에 쓰이지 않습니다.')) archive.mutate(version.id)
  }

  const handleSaveExpiry = () => {
    if (!expiryValue) return
    setExpiry.mutate({ id: documentId, expiresAt: endOfLocalDayIso(expiryValue) }, {
      onSuccess: () => setExpiryDraft(null),
    })
  }

  const handleClearExpiry = () => {
    setExpiry.mutate({ id: documentId, expiresAt: null }, { onSuccess: () => setExpiryDraft(null) })
  }

  return (
    <section aria-label="문서 버전 이력" style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
      <h3 style={{ fontSize: 14, margin: 0 }}>문서 버전</h3>
      <p style={{ fontSize: 12, color: 'var(--color-text-muted)', margin: 0 }}>
        같은 이름의 문서를 새 내용으로 올리면 새 버전이 됩니다. 검색에는 현재 버전만 쓰입니다.
      </p>

      <ol style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
        {items.map((version) => (
          <li key={version.id} style={{ border: '1px solid var(--color-border)', borderRadius: 'var(--radius-md)', padding: 'var(--space-2) var(--space-3)', display: 'flex', flexDirection: 'column', gap: 4 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', flexWrap: 'wrap' }}>
              <strong style={{ fontSize: 13 }}>{version.version_number}번 버전</strong>
              <span className="ds-badge ds-badge--neutral">{LIFECYCLE_STATE_LABELS[version.lifecycle_state]}</span>
              <span style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
                {STATUS_LABELS[version.status] ?? version.status} · {new Date(version.created_at).toLocaleDateString('ko-KR')}
              </span>
              {version.is_retrievable && <span className="ds-badge ds-badge--success">검색에 쓰임</span>}
              {version.id === documentId && <span style={{ fontSize: 12, color: 'var(--color-accent)' }}>지금 보는 문서</span>}
            </div>
            <div style={{ display: 'flex', gap: 'var(--space-2)', flexWrap: 'wrap' }}>
              {canRestore(version) && (
                <button type="button" className="ds-btn ds-btn--secondary ds-btn--sm" disabled={restore.isPending} onClick={() => handleRestore(version)}>
                  이 버전을 현재 버전으로
                </button>
              )}
              {version.lifecycle_state === 'current' && (
                <button type="button" className="ds-btn ds-btn--secondary ds-btn--sm" disabled={archive.isPending} onClick={() => handleArchive(version)}>
                  보관
                </button>
              )}
              {current && version.id !== current.id && (
                <button
                  type="button"
                  className="ds-btn ds-btn--ghost ds-btn--sm"
                  aria-pressed={compareId === version.id}
                  onClick={() => setCompareId(compareId === version.id ? null : version.id)}
                >
                  {compareId === version.id ? '비교 닫기' : '현재 버전과 비교'}
                </button>
              )}
            </div>
          </li>
        ))}
      </ol>

      {!current && items.length > 0 && (
        <p style={{ fontSize: 12, color: 'var(--color-text-muted)', margin: 0 }}>현재 버전이 없어 비교할 수 없습니다.</p>
      )}
      {compareBaseId && current && <VersionDiff baseId={compareBaseId} currentId={current.id} />}

      <ErrorText message={restore.isError ? apiErrorDetail(restore.error, '되돌리지 못했습니다.') : null} />
      <ErrorText message={archive.isError ? apiErrorDetail(archive.error, '보관하지 못했습니다.') : null} />

      {pageItem && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
          <label htmlFor="document_expiry" style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
            만료일 (이 날 끝나면 자동으로 보관됩니다)
          </label>
          <div style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'center', flexWrap: 'wrap' }}>
            <input
              id="document_expiry"
              type="date"
              value={expiryValue}
              onChange={(e) => setExpiryDraft(e.target.value)}
              className="ds-input"
            />
            <button type="button" className="ds-btn ds-btn--primary ds-btn--sm" disabled={setExpiry.isPending || !expiryValue || expiryValue === serverExpiry} onClick={handleSaveExpiry}>
              만료일 저장
            </button>
            {pageItem.expires_at && (
              <button type="button" className="ds-btn ds-btn--ghost ds-btn--sm" disabled={setExpiry.isPending} onClick={handleClearExpiry}>
                만료일 지우기
              </button>
            )}
          </div>
          <ErrorText message={setExpiry.isError ? apiErrorDetail(setExpiry.error, '만료일을 저장하지 못했습니다.') : null} />
        </div>
      )}
    </section>
  )
}
