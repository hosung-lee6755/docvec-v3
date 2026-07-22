import { useNavigate } from 'react-router-dom'
import { Loader2, AlertTriangle } from 'lucide-react'
import { useProcessingStats } from '../hooks/useProcessingStats'
import { getBlockMeta } from '../lib/workflowBlocks'

const FAILURE_RATE_WARNING_THRESHOLD = 0.05

function formatPercent(value: number): string {
  return `${(value * 100).toFixed(1)}%`
}

function formatSeconds(value: number | null): string {
  if (value == null) return '-'
  return value < 60 ? `${value.toFixed(1)}초` : `${(value / 60).toFixed(1)}분`
}

export default function ProcessingStatusPage() {
  const navigate = useNavigate()
  const { data, isLoading } = useProcessingStats()

  if (isLoading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: 'var(--space-8)' }}>
        <Loader2 size={20} style={{ animation: 'spin 1s linear infinite', color: 'var(--color-text-muted)' }} />
      </div>
    )
  }

  const tiles = [
    { label: '처리 문서', value: data?.processed_documents ?? 0 },
    { label: '평균 품질', value: data?.avg_quality != null ? data.avg_quality.toFixed(1) : '-' },
    { label: '실패율', value: formatPercent(data?.failure_rate ?? 0) },
    { label: '재처리율', value: formatPercent(data?.reprocess_rate ?? 0) },
    {
      label: '검토 대기', value: data?.waiting_review_count ?? 0,
      warn: (data?.waiting_review_count ?? 0) > 0,
      onClick: () => navigate('/documents?status=WAITING_REVIEW'),
    },
    { label: '큐 대기', value: formatSeconds(data?.avg_queue_seconds ?? null) },
  ]

  return (
    <div>
      <style>{`@keyframes spin { to { transform: rotate(360deg) } }`}</style>
      <div style={{ marginBottom: 'var(--space-6)' }}>
        <h1 style={{ fontSize: 24, fontWeight: 700, margin: '0 0 4px' }}>문서 처리 현황</h1>
        <p style={{ fontSize: 13, color: 'var(--color-text-muted)', margin: 0 }}>최근 24시간</p>
      </div>

      <div style={{
        display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
        gap: 'var(--space-3)', marginBottom: 'var(--space-6)',
      }}>
        {tiles.map((tile) => (
          <div
            key={tile.label}
            onClick={tile.onClick}
            style={{
              padding: 'var(--space-4)', background: 'var(--color-surface)',
              border: `1px solid ${tile.warn ? '#f59e0b' : 'var(--color-border)'}`,
              borderRadius: 'var(--radius-md)', cursor: tile.onClick ? 'pointer' : 'default',
            }}
          >
            <div style={{ fontSize: 12, color: 'var(--color-text-muted)', marginBottom: 6 }}>{tile.label}</div>
            <div style={{ fontSize: 24, fontWeight: 700, color: tile.warn ? '#f59e0b' : 'var(--color-text)' }}>
              {tile.value}
            </div>
          </div>
        ))}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(320px, 1.2fr) minmax(280px, 1fr)', gap: 'var(--space-4)' }}>
        <div style={{ padding: 'var(--space-4)', background: 'var(--color-surface)', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-md)' }}>
          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 'var(--space-3)', color: 'var(--color-text)' }}>블록별 성능</div>
          {!data?.block_stats.length && (
            <p style={{ fontSize: 13, color: 'var(--color-text-muted)', margin: 0 }}>기간 내 실행된 블록이 없습니다.</p>
          )}
          {!!data?.block_stats.length && (
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                <thead>
                  <tr style={{ background: 'rgba(148,163,184,0.08)' }}>
                    {['블록', '실행', '실패율', '평균시간'].map((h) => (
                      <th key={h} style={{ textAlign: 'left', padding: '6px 10px', borderBottom: '1px solid var(--color-border)', color: 'var(--color-text)' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.block_stats.map((b) => {
                    const warn = b.failure_rate > FAILURE_RATE_WARNING_THRESHOLD
                    return (
                      <tr key={b.block_type}>
                        <td style={{ padding: '6px 10px', borderBottom: '1px solid var(--color-border)', color: 'var(--color-text)' }}>
                          {getBlockMeta(b.block_type).label}
                        </td>
                        <td style={{ padding: '6px 10px', borderBottom: '1px solid var(--color-border)', color: 'var(--color-text)' }}>{b.execution_count}</td>
                        <td style={{ padding: '6px 10px', borderBottom: '1px solid var(--color-border)', color: warn ? '#f59e0b' : 'var(--color-text)' }}>
                          {warn && <AlertTriangle size={11} style={{ marginRight: 4, verticalAlign: 'text-bottom' }} />}
                          {formatPercent(b.failure_rate)}
                        </td>
                        <td style={{ padding: '6px 10px', borderBottom: '1px solid var(--color-border)', color: 'var(--color-text)' }}>
                          {formatSeconds(b.avg_duration_seconds)}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div style={{ padding: 'var(--space-4)', background: 'var(--color-surface)', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-md)' }}>
          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 'var(--space-3)', color: 'var(--color-text)' }}>최근 실패</div>
          {!data?.recent_failures.length && (
            <p style={{ fontSize: 13, color: 'var(--color-text-muted)', margin: 0 }}>최근 실패한 처리가 없습니다.</p>
          )}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
            {data?.recent_failures.map((f) => (
              <div
                key={`${f.document_id}-${f.created_at}`}
                onClick={() => navigate(`/documents/${f.document_id}`)}
                style={{
                  display: 'flex', flexDirection: 'column', gap: 2, cursor: 'pointer',
                  padding: 'var(--space-2)', borderRadius: 'var(--radius-sm)',
                }}
              >
                <span style={{ fontSize: 13, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: 'var(--color-text)' }}>
                  {f.filename}
                </span>
                <span style={{ fontSize: 11, color: '#dc2626' }}>{f.error_message ?? '오류 메시지 없음'}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
