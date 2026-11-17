import type { GoldenEvalQueryResult, GoldenEvalRun } from '../../hooks/useGoldenQueries'
import { Alert, Stat, StatStrip } from '../ui'
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
    <Alert tone="danger">
      <strong>기준 실행보다 검색 품질이 떨어졌습니다.</strong>
      <ul style={{ margin: 'var(--space-1) 0 0', paddingLeft: 'var(--space-4)' }}>
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
        <div style={{ marginTop: 'var(--space-2)' }}>
          기준에서는 맞혔지만 이번에 놓친 질문 {regression.lost_queries.length}개:
          <ul style={{ margin: 'var(--space-1) 0 0', paddingLeft: 'var(--space-4)' }}>
            {regression.lost_queries.map((lost) => <li key={lost.golden_query_id}>{lost.query}</li>)}
          </ul>
        </div>
      )}
    </Alert>
  )
}

// 답변까지 평가한 실행의 질문별 결과. 놓친 사실을 먼저 보여 주고, 답 본문은 펼쳐서 본다.
function AnswerFacts({ result }: { result: GoldenEvalQueryResult }) {
  if (!result.expected_facts?.length) return <span className="ds-cell-muted">기대 사실 없음</span>
  if (result.answer_status === 'FAILED') return <span>답을 만들지 못했습니다</span>
  const found = new Set(result.facts_found ?? [])
  const missed = result.expected_facts.filter((fact) => !found.has(fact))
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-1)' }}>
      <span>
        {found.size} / {result.expected_facts.length} ({formatPercent(result.fact_recall)})
      </span>
      {missed.length > 0 && <span className="ds-cell-sub">놓친 사실: {missed.join(', ')}</span>}
      {result.answer && (
        <details>
          <summary style={{ cursor: 'pointer', fontSize: 'var(--text-xs)' }}>답 보기</summary>
          <p style={{ margin: 'var(--space-1) 0 0', whiteSpace: 'pre-wrap', fontSize: 'var(--text-xs)' }}>{result.answer}</p>
        </details>
      )}
    </div>
  )
}

export default function GoldenRunDetail({ run, filenameFor }: GoldenRunDetailProps) {
  if (!run.results) {
    return (
      <p style={{ fontSize: 'var(--text-sm)', color: 'var(--color-text-muted)', margin: 0 }}>
        {run.status === 'FAILED' ? '평가하지 못했습니다.' : '평가가 끝나면 질문별 결과가 나옵니다.'}
      </p>
    )
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
      <RegressionBanner run={run} />
      <StatStrip label="평가 지표">
        <Stat label="정밀도(Precision)" value={formatPercent(run.mean_precision)} />
        <Stat label="재현율(Recall)" value={formatPercent(run.mean_recall)} />
        <Stat label="적중률(Hit rate)" value={formatPercent(run.mean_hit_rate)} />
        <Stat label="MRR" value={formatPercent(run.mean_mrr)} />
        {run.with_answers && <Stat label="사실 적중률(답변)" value={formatPercent(run.mean_fact_recall)} />}
      </StatStrip>
      <div className="ds-table-wrap" style={{ maxHeight: 220, overflowY: 'auto' }}>
        <table className="ds-table ds-table--compact" aria-label="질문별 평가 결과">
          <thead>
            <tr>
              <th scope="col">질문</th>
              <th scope="col">적중</th>
              <th scope="col">첫 적중 순위</th>
              <th scope="col">Precision</th>
              <th scope="col">Recall</th>
              <th scope="col">기대/조회 문서</th>
              {run.with_answers && <th scope="col">답변의 기대 사실</th>}
            </tr>
          </thead>
          <tbody>
            {run.results.map((r) => (
              <tr key={r.golden_query_id}>
                <td>
                  {r.query}
                  {r.masked && <span className="ds-cell-sub">권한 밖 문서가 있어 점수를 가렸습니다</span>}
                </td>
                <td>{HIT_LABEL[hitKey(r.hit)]}</td>
                <td className="ds-cell-num">{r.first_hit_rank ?? '-'}</td>
                <td className="ds-cell-num">{formatPercent(r.precision)}</td>
                <td className="ds-cell-num">{formatPercent(r.recall)}</td>
                <td className="ds-cell-muted">
                  기대: {r.expected_document_ids.map(filenameFor).join(', ')}
                  <br />조회: {r.retrieved_document_ids.map(filenameFor).join(', ') || '—'}
                </td>
                {run.with_answers && <td><AnswerFacts result={r} /></td>}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
