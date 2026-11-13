import { AlertTriangle, Loader2 } from 'lucide-react'
import { ErrorText } from '../ui'
import {
  useDictionaryApplications,
  useDictionaryExclusions,
  useRevertDictionaryApplication,
  useToggleDictionaryExclusion,
  type DictionaryApplicationItem,
} from '../../hooks/useDocumentStructure'

const DICTIONARY_TYPE_LABELS: Record<string, string> = {
  STOPWORD: '불용어', SYNONYM: '동의어', USER_DICT: '사용자사전',
}

// 사전 항목 자체의 유형(dictionary_entries.entry_type)
const ENTRY_TYPE_LABELS: Record<string, string> = {
  stopword: '불용어', synonym: '동의어', custom_word: '사용자사전',
}

const CELL: React.CSSProperties = { padding: '6px 10px', borderBottom: '1px solid var(--color-surface-muted)', verticalAlign: 'top' }

interface DictionaryApplicationsTabProps {
  documentId: string
  onReprocessFromDictionary: () => void
}

interface EntrySummary {
  entryId: string
  term: string
  kind: string
  count: number
}

// 사전 항목별로 묶어 "이 문서에서 끄기"를 한 번에 할 수 있게 한다(v3 마일스톤 6)
function summarizeEntries(applications: DictionaryApplicationItem[]): EntrySummary[] {
  const byEntry = new Map<string, EntrySummary>()
  for (const app of applications) {
    if (!app.entry_id) continue
    const current = byEntry.get(app.entry_id)
    byEntry.set(app.entry_id, {
      entryId: app.entry_id,
      term: app.entry_term ?? app.normalized_text ?? app.original_text,
      kind: DICTIONARY_TYPE_LABELS[app.dictionary_type] ?? app.dictionary_type,
      count: (current?.count ?? 0) + 1,
    })
  }
  return [...byEntry.values()].sort((a, b) => b.count - a.count)
}

function InContext({ app }: { app: DictionaryApplicationItem }) {
  const changed = app.normalized_text && app.normalized_text !== app.original_text
  return (
    <span style={{ lineHeight: 1.6 }}>
      {app.context_before ? <span style={{ color: 'var(--color-text-muted)' }}>…{app.context_before}</span> : null}
      <mark style={{ background: 'var(--color-highlight)', padding: '0 2px', borderRadius: 2 }}>
        {changed ? <><s>{app.original_text}</s> → {app.normalized_text}</> : app.original_text}
      </mark>
      {app.context_after ? <span style={{ color: 'var(--color-text-muted)' }}>{app.context_after}…</span> : null}
      {!changed && <span style={{ marginLeft: 6, color: 'var(--color-text-muted)' }}>(바꾸지 않고 표시만)</span>}
    </span>
  )
}

export default function DictionaryApplicationsTab({
  documentId, onReprocessFromDictionary,
}: DictionaryApplicationsTabProps) {
  const { data, isLoading } = useDictionaryApplications(documentId)
  const revert = useRevertDictionaryApplication()
  const toggle = useToggleDictionaryExclusion()
  const { data: exclusions } = useDictionaryExclusions(documentId)

  if (isLoading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: 'var(--space-6)' }}>
        <Loader2 size={20} style={{ animation: 'spin 1s linear infinite', color: 'var(--color-text-muted)' }} />
      </div>
    )
  }

  const applications = data?.applications ?? []
  const excluded = new Set(data?.excluded_entry_ids ?? [])
  if (!applications.length && !excluded.size) {
    return <p style={{ color: 'var(--color-text-muted)', fontSize: 13, margin: 0 }}>사전 적용 내역이 없습니다.</p>
  }
  const applied = summarizeEntries(applications)
  // 재처리로 이미 반영된(적용 기록이 없는) 끈 항목도 다시 켤 수 있게 목록에 붙인다
  const appliedIds = new Set(applied.map((e) => e.entryId))
  const offOnly: EntrySummary[] = (exclusions?.entries ?? [])
    .filter((x) => !appliedIds.has(x.entry_id))
    .map((x) => ({
      entryId: x.entry_id, term: x.term ?? '(삭제된 항목)',
      kind: ENTRY_TYPE_LABELS[x.entry_type ?? ''] ?? '사전', count: 0,
    }))
  const entries = [...applied, ...offOnly]
  // 끈 항목 중 아직 이 처리 결과에 남아 있는 것만 재처리가 필요하다
  const pendingExclusions = applied.filter((e) => excluded.has(e.entryId)).length
  const needsReprocess = (data?.pending_revert_count ?? 0) > 0 || pendingExclusions > 0

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
      <p style={{ fontSize: 12, color: 'var(--color-text-muted)', margin: 0 }}>
        적용 {applications.length}건 · 사전 버전 v{applications[0]?.dictionary_version ?? '-'}
      </p>

      {entries.length > 0 && (
        <section aria-label="이 문서에 적용된 사전 항목">
          <h3 style={{ fontSize: 13, margin: '0 0 var(--space-2)' }}>이 문서에 적용된 사전 항목</h3>
          <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexWrap: 'wrap', gap: 'var(--space-2)' }}>
            {entries.map((e) => {
              const isOff = excluded.has(e.entryId)
              return (
                <li key={e.entryId} style={{
                  display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, padding: '4px 8px',
                  border: '1px solid var(--color-border)', borderRadius: 999, opacity: isOff ? 0.6 : 1,
                }}>
                  <span className="ds-badge ds-badge--neutral">{e.kind}</span>
                  <span style={{ textDecoration: isOff ? 'line-through' : 'none' }}>{e.term}</span>
                  <span style={{ color: 'var(--color-text-muted)' }}>{e.count ? `${e.count}건` : '적용 안 됨'}</span>
                  <button type="button" className="ds-btn ds-btn--ghost ds-btn--sm" disabled={toggle.isPending}
                    onClick={() => toggle.mutate({ documentId, entryId: e.entryId, exclude: !isOff })}>
                    {isOff ? '다시 적용' : '이 문서에서 끄기'}
                  </button>
                </li>
              )
            })}
          </ul>
          {revert.isError && <ErrorText error={revert.error} message="적용을 취소하지 못했습니다." />}
          {toggle.isError && (
            <p style={{ margin: 'var(--space-1) 0 0' }}>
              <ErrorText error={toggle.error} message="사전 적용 여부를 바꾸지 못했습니다." />
            </p>
          )}
        </section>
      )}

      <div style={{ overflowX: 'auto', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-sm)' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead>
            <tr style={{ background: 'var(--color-surface-subtle)' }}>
              {['유형', '사전 항목', '바뀐 자리', '사전버전', '작업'].map((h) => (
                <th key={h} style={{ textAlign: 'left', padding: '6px 10px', borderBottom: '1px solid var(--color-border)' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {applications.map((app) => (
              <tr key={app.id}>
                <td style={CELL}>{DICTIONARY_TYPE_LABELS[app.dictionary_type] ?? app.dictionary_type}</td>
                <td style={CELL}>{app.entry_term ?? '-'}</td>
                <td style={CELL}><InContext app={app} /></td>
                <td style={CELL}>v{app.dictionary_version}</td>
                <td style={CELL}>
                  {app.reverted ? (
                    <span className="ds-badge ds-badge--neutral">취소됨</span>
                  ) : (
                    <button
                      type="button"
                      onClick={() => revert.mutate({ documentId, appId: app.id })}
                      disabled={revert.isPending}
                      className="ds-btn ds-btn--ghost ds-btn--sm"
                      title="이 문서에서 같은 표현은 다음 처리부터 바꾸지 않습니다"
                    >
                      적용 취소
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {needsReprocess && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 'var(--space-2)',
          padding: 'var(--space-2) var(--space-3)', background: 'var(--color-warning-bg)',
          border: '1px solid var(--color-warning-border)', borderRadius: 'var(--radius-sm)', fontSize: 12, color: 'var(--color-warning)',
        }}>
          <AlertTriangle size={14} />
          <span style={{ flex: 1 }}>
            {(data?.pending_revert_count ?? 0) > 0 && `적용 취소 ${data?.pending_revert_count}건`}
            {(data?.pending_revert_count ?? 0) > 0 && pendingExclusions > 0 && ', '}
            {pendingExclusions > 0 && `이 문서에서 끈 항목 ${pendingExclusions}개`}
            {'. 사전 블록부터 다시 처리해야 본문에 반영됩니다.'}
          </span>
          <button
            type="button"
            onClick={onReprocessFromDictionary}
            className="ds-btn ds-btn--secondary ds-btn--sm"
          >
            사전 블록부터 재처리
          </button>
        </div>
      )}
    </div>
  )
}
