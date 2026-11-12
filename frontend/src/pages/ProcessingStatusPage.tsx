import { useNavigate } from 'react-router-dom'
import { AlertTriangle } from 'lucide-react'
import { useProcessingStats } from '../hooks/useProcessingStats'
import { getBlockMeta } from '../lib/workflowBlocks'
import { Card, Page, PageHeader, Spinner, Stat, StatStrip } from '../components/ui'
import '../styles/screens/documents.css'

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
      <Page>
        <PageHeader title="문서 처리 현황" subtitle="최근 24시간" />
        <div className="documents-center"><Spinner /></div>
      </Page>
    )
  }

  const waitingCount = data?.waiting_review_count ?? 0

  return (
    <Page>
      <PageHeader title="문서 처리 현황" subtitle="최근 24시간" />

      <StatStrip>
        <Stat label="처리 문서" value={data?.processed_documents ?? 0} />
        <Stat label="평균 품질" value={data?.avg_quality != null ? data.avg_quality.toFixed(1) : '-'} />
        <Stat label="실패율" value={formatPercent(data?.failure_rate ?? 0)} />
        <Stat label="재처리율" value={formatPercent(data?.reprocess_rate ?? 0)} />
        <Stat
          label="검토 대기"
          value={waitingCount}
          tone={waitingCount > 0 ? 'warning' : 'default'}
          onClick={() => navigate('/documents?status=WAITING_REVIEW')}
        />
        <Stat label="큐 대기" value={formatSeconds(data?.avg_queue_seconds ?? null)} />
      </StatStrip>

      <div className="documents-grid-2">
        <Card title="블록별 성능">
          {!data?.block_stats.length ? (
            <p className="documents-note">기간 내 실행된 블록이 없습니다.</p>
          ) : (
            <div className="ds-table-wrap">
              <table className="ds-table ds-table--compact">
                <thead>
                  <tr>
                    <th scope="col">블록</th>
                    <th scope="col" className="ds-cell-num">실행</th>
                    <th scope="col" className="ds-cell-num">실패율</th>
                    <th scope="col" className="ds-cell-num">평균시간</th>
                  </tr>
                </thead>
                <tbody>
                  {data.block_stats.map((b) => {
                    const isWarn = b.failure_rate > FAILURE_RATE_WARNING_THRESHOLD
                    return (
                      <tr key={b.block_type} className={isWarn ? 'is-warning' : undefined}>
                        <td>{getBlockMeta(b.block_type).label}</td>
                        <td className="ds-cell-num">{b.execution_count}</td>
                        <td className="ds-cell-num">
                          {isWarn && <AlertTriangle size={11} aria-hidden="true" style={{ marginRight: 4, verticalAlign: 'text-bottom' }} />}
                          {formatPercent(b.failure_rate)}
                        </td>
                        <td className="ds-cell-num">{formatSeconds(b.avg_duration_seconds)}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        <Card title="최근 실패">
          {!data?.recent_failures.length ? (
            <p className="documents-note">최근 실패한 처리가 없습니다.</p>
          ) : (
            <div className="documents-stack">
              {data.recent_failures.map((f) => (
                <div key={`${f.document_id}-${f.created_at}`} className="documents-row-fail">
                  <button
                    type="button"
                    className="documents-link documents-ellipsis"
                    onClick={() => navigate(`/documents/${f.document_id}`)}
                  >
                    {f.filename}
                  </button>
                  <span className="documents-text-danger" style={{ fontSize: 'var(--text-xs)' }}>
                    {f.error_message ?? '오류 메시지 없음'}
                  </span>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>
    </Page>
  )
}
