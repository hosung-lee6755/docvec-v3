import type { GoldenEvalRun } from '../../hooks/useGoldenQueries'
import { REGRESSED_METRIC_LABELS, formatPercent } from './goldenLabels'

interface GoldenRunDetailProps {
  run: GoldenEvalRun
  filenameFor: (docId: string) => string
}

const HIT_LABEL: Record<'hit' | 'miss' | 'none', string> = { hit: '맞힘', miss: '놓침', none: '-' }

function hitKey(hit: boolean | null | undefined): keyof typeof HIT_LABEL {
  if (hit === true) return 'hit'
  if (hit === false) return 'miss'
  return 'none'
}

// 회귀 배너: 기준 실행보다 떨어진 지표와, 기준에서는 맞혔는데 이번에 놓친 질의를 보여준다.
function RegressionBanner({ run }: { run: GoldenEvalRun }) {
  const regression = run.regression
  if (!run.is_regression || !regression) return null
  return (
    <div role="alert" style={{ background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 'var(--radius-md)', padding: 'var(--space-3)', fontSize: 13, color: '#991b1b', display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
      <strong>기준 실행보다 검색 품질이 떨어졌습니다.</strong>
      <ul style={{ margin: 0, paddingLeft: 'var(--space-4)' }}>
        {regression.regressed_metrics.map((metric) => {
          const values = regression.metrics[metric]
          return (
            <li key={metric}>
              {REGRESSED_METRIC_LABELS[metric]}: {formatPercent(values?.baseline)} → {formatPercent(values?.current)}
            </li>
          )
        })}
      </ul>
      {regression.lost_queries.length > 0 && (
        <div>
          기준에서는 맞혔지만 이번에 놓친 질문 {regression.lost_queries.length}개:
          <ul style={{ margin: 'var(--space-1) 0 0', paddingLeft: 'var(--space-4)' }}>
            {regression.lost_queries.map((lost) => <li key={lost.golden_query_id}>{lost.query}</li>)}
          </ul>
        </div>
      )}
    </div>
  )
}

export default function GoldenRunDetail({ run, filenameFor }: GoldenRunDetailProps) {
  if (!run.results) {
    return (
      <p style={{ fontSize: 12, color: 'var(--color-text-muted)', margin: 0 }}>
        {run.status === 'FAILED' ? '평가하지 못했습니다.' : '평가가 끝나면 질문별 결과가 나옵니다.'}
      </p>
    )
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
      <RegressionBanner run={run} />
      <div style={{ display: 'flex', gap: 'var(--space-4)', fontSize: 13, flexWrap: 'wrap' }}>
        <span>정밀도(Precision): <strong>{formatPercent(run.mean_precision)}</strong></span>
        <span>재현율(Recall): <strong>{formatPercent(run.mean_recall)}</strong></span>
        <span>적중률(Hit rate): <strong>{formatPercent(run.mean_hit_rate)}</strong></span>
        <span>MRR: <strong>{formatPercent(run.mean_mrr)}</strong></span>
      </div>
      <div style={{ maxHeight: 220, overflowY: 'auto', border: '1px solid #e2e8f0', borderRadius: 'var(--radius-md)' }}>
        <table className="krds-table" style={{ width: '100%', fontSize: 12 }}>
          <thead>
            <tr>
              <th>질문</th><th>적중</th><th>첫 적중 순위</th><th>Precision</th><th>Recall</th><th>기대/조회 문서</th>
            </tr>
          </thead>
          <tbody>
            {run.results.map((r) => (
              <tr key={r.golden_query_id}>
                <td>{r.query}{r.masked && <span style={{ color: 'var(--color-text-muted)', fontSize: 11 }}> (권한 밖 문서가 있어 점수를 가렸습니다)</span>}</td>
                <td>{HIT_LABEL[hitKey(r.hit)]}</td>
                <td>{r.first_hit_rank ?? '-'}</td>
                <td>{formatPercent(r.precision)}</td>
                <td>{formatPercent(r.recall)}</td>
                <td style={{ color: 'var(--color-text-muted)' }}>
                  기대: {r.expected_document_ids.map(filenameFor).join(', ')}
                  <br />조회: {r.retrieved_document_ids.map(filenameFor).join(', ') || '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
