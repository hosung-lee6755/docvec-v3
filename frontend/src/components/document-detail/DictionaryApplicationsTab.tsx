import { AlertTriangle, Loader2 } from 'lucide-react'
import { useDictionaryApplications, useRevertDictionaryApplication } from '../../hooks/useDocumentStructure'

const DICTIONARY_TYPE_LABELS: Record<string, string> = {
  STOPWORD: '불용어', SYNONYM: '동의어', USER_DICT: '사용자사전',
}

interface DictionaryApplicationsTabProps {
  documentId: string
  onReprocessFromDictionary: () => void
}

export default function DictionaryApplicationsTab({
  documentId, onReprocessFromDictionary,
}: DictionaryApplicationsTabProps) {
  const { data, isLoading } = useDictionaryApplications(documentId)
  const revert = useRevertDictionaryApplication()

  if (isLoading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: 'var(--space-6)' }}>
        <Loader2 size={20} style={{ animation: 'spin 1s linear infinite', color: 'var(--color-text-muted)' }} />
      </div>
    )
  }

  const applications = data?.applications ?? []
  if (!applications.length) {
    return <p style={{ color: 'var(--color-text-muted)', fontSize: 13, margin: 0 }}>사전 적용 내역이 없습니다.</p>
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
      <p style={{ fontSize: 12, color: 'var(--color-text-muted)', margin: 0 }}>
        적용 {applications.length}건 · 사전 버전 v{applications[0]?.dictionary_version ?? '-'}
      </p>
      <div style={{ overflowX: 'auto', border: '1px solid #e2e8f0', borderRadius: 'var(--radius-sm)' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead>
            <tr style={{ background: '#f8fafc' }}>
              {['유형', '원문 → 결과', '위치', '사전버전', '작업'].map((h) => (
                <th key={h} style={{ textAlign: 'left', padding: '6px 10px', borderBottom: '1px solid #e2e8f0' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {applications.map((app) => (
              <tr key={app.id}>
                <td style={{ padding: '6px 10px', borderBottom: '1px solid #f1f5f9' }}>
                  {DICTIONARY_TYPE_LABELS[app.dictionary_type] ?? app.dictionary_type}
                </td>
                <td style={{ padding: '6px 10px', borderBottom: '1px solid #f1f5f9' }}>
                  {app.original_text} → {app.normalized_text ?? '(분석 제외 표시)'}
                </td>
                <td style={{ padding: '6px 10px', borderBottom: '1px solid #f1f5f9', color: 'var(--color-text-muted)' }}>
                  {app.node_id ? app.node_id.slice(0, 8) : '전체'}
                </td>
                <td style={{ padding: '6px 10px', borderBottom: '1px solid #f1f5f9' }}>v{app.dictionary_version}</td>
                <td style={{ padding: '6px 10px', borderBottom: '1px solid #f1f5f9' }}>
                  {app.reverted ? (
                    <span className="krds-badge xsmall bg-gray">취소됨</span>
                  ) : (
                    <button
                      type="button"
                      onClick={() => revert.mutate({ documentId, appId: app.id })}
                      disabled={revert.isPending}
                      className="krds-btn text xsmall"
                      style={{ cursor: 'pointer' }}
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
      {(data?.pending_revert_count ?? 0) > 0 && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 'var(--space-2)',
          padding: 'var(--space-2) var(--space-3)', background: '#fffbeb',
          border: '1px solid #fde68a', borderRadius: 'var(--radius-sm)', fontSize: 12, color: '#92400e',
        }}>
          <AlertTriangle size={14} />
          <span style={{ flex: 1 }}>
            적용 취소 {data?.pending_revert_count}건 대기 중 — 반영하려면 재처리가 필요합니다
          </span>
          <button
            type="button"
            onClick={onReprocessFromDictionary}
            className="krds-btn secondary xsmall"
            style={{ cursor: 'pointer' }}
          >
            사전 블록부터 재처리
          </button>
        </div>
      )}
    </div>
  )
}
