import { Fragment, useState } from 'react'
import { Loader2 } from 'lucide-react'
import { useCleaningChanges } from '../../hooks/useDocumentStructure'

export default function CleaningChangesTab({ documentId }: { documentId: string }) {
  const { data, isLoading } = useCleaningChanges(documentId)
  const [expandedId, setExpandedId] = useState<string | null>(null)

  if (isLoading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: 'var(--space-6)' }}>
        <Loader2 size={20} style={{ animation: 'spin 1s linear infinite', color: 'var(--color-text-muted)' }} />
      </div>
    )
  }

  const changes = data?.changes ?? []
  if (!changes.length) {
    return <p style={{ color: 'var(--color-text-muted)', fontSize: 13, margin: 0 }}>정제 변경 내역이 없습니다.</p>
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
      <p style={{ fontSize: 12, color: 'var(--color-text-muted)', margin: 0 }}>
        변경 {data?.total_changes ?? 0}건 · 규칙 {data?.distinct_rule_count ?? 0}종
      </p>
      <div style={{ overflowX: 'auto', border: '1px solid #e2e8f0', borderRadius: 'var(--radius-sm)' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead>
            <tr style={{ background: '#f8fafc' }}>
              {['규칙', '위치', '정제 전', '정제 후', '건수', ''].map((h) => (
                <th key={h} style={{ textAlign: 'left', padding: '6px 10px', borderBottom: '1px solid #e2e8f0' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {changes.map((c) => (
              <Fragment key={c.id}>
                <tr>
                  <td style={{ padding: '6px 10px', borderBottom: '1px solid #f1f5f9' }}>
                    {c.rule_name ?? c.rule_key ?? '-'}
                  </td>
                  <td style={{ padding: '6px 10px', borderBottom: '1px solid #f1f5f9', color: 'var(--color-text-muted)' }}>
                    {c.node_id ? c.node_id.slice(0, 8) : '전체'}
                  </td>
                  <td style={{ padding: '6px 10px', borderBottom: '1px solid #f1f5f9', maxWidth: 240, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {c.before_sample ?? '-'}
                  </td>
                  <td style={{ padding: '6px 10px', borderBottom: '1px solid #f1f5f9', maxWidth: 240, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {c.after_sample ?? '(제거됨)'}
                  </td>
                  <td style={{ padding: '6px 10px', borderBottom: '1px solid #f1f5f9' }}>{c.change_count}</td>
                  <td style={{ padding: '6px 10px', borderBottom: '1px solid #f1f5f9' }}>
                    {!!c.sample_matches?.length && (
                      <button
                        type="button"
                        onClick={() => setExpandedId(expandedId === c.id ? null : c.id)}
                        className="krds-btn text xsmall"
                        style={{ cursor: 'pointer' }}
                      >
                        {expandedId === c.id ? '접기' : '상세'}
                      </button>
                    )}
                  </td>
                </tr>
                {expandedId === c.id && !!c.sample_matches?.length && (
                  <tr>
                    <td colSpan={6} style={{ padding: '8px 12px', borderBottom: '1px solid #f1f5f9', background: 'rgba(148,163,184,0.06)' }}>
                      <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginBottom: 4 }}>
                        발생 위치 {c.sample_matches.length}건{c.change_count > c.sample_matches.length ? ` (전체 ${c.change_count}건 중 일부)` : ''}
                      </div>
                      <ul style={{ margin: 0, paddingLeft: 18, display: 'flex', flexDirection: 'column', gap: 2 }}>
                        {c.sample_matches.map((sample, i) => (
                          <li key={i} style={{ fontFamily: 'monospace', fontSize: 11, wordBreak: 'break-all' }}>{sample}</li>
                        ))}
                      </ul>
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
