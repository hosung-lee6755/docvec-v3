import { ShieldOff } from 'lucide-react'
import { useUsageSummary } from '../hooks/useUsage'
import { useAuthStore } from '../store/authStore'
import {
  Alert, EmptyState, Page, PageBody, PageHeader, Spinner, Stat, StatStrip,
} from '../components/ui'

function formatCost(cost: number): string {
  return `$${cost.toFixed(4)}`
}

function formatTokens(tokens: number): string {
  return tokens.toLocaleString('en-US')
}

export default function UsageDashboardPage() {
  const currentUser = useAuthStore((s) => s.user)
  const { data, isLoading, isError } = useUsageSummary()

  if (currentUser?.role !== 'admin') {
    return (
      <Page>
        <EmptyState icon={<ShieldOff size={48} aria-hidden="true" />} title="관리자만 접근할 수 있습니다." />
      </Page>
    )
  }

  return (
    <Page>
      <PageHeader
        title="BYOK 사용량 대시보드"
        subtitle="클라우드 LLM(OpenAI/Anthropic) 호출의 토큰 사용량과 추정 비용입니다. 로컬 모델(Qwen2.5)은 비용이 없어 집계에서 제외됩니다. 가격은 공개 요율 기준 추정치입니다."
      />

      {isLoading && (
        <PageBody>
          <div style={{ display: 'flex', justifyContent: 'center', padding: 'var(--space-8)' }}><Spinner /></div>
        </PageBody>
      )}

      {isError && (
        <PageBody>
          <Alert tone="danger">사용량 데이터를 불러오지 못했습니다.</Alert>
        </PageBody>
      )}

      {!isLoading && !isError && data && (
        <>
          <StatStrip>
            <Stat label="총 요청 수" value={data.summary.total_requests.toLocaleString('en-US')} />
            <Stat label="입력 토큰" value={formatTokens(data.summary.total_input_tokens)} />
            <Stat label="출력 토큰" value={formatTokens(data.summary.total_output_tokens)} />
            <Stat label="추정 비용" value={formatCost(data.summary.total_cost_usd)} />
          </StatStrip>

          <PageBody>
            <section aria-label="모델별 사용량" style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
              <h2 className="ds-section-title" style={{ fontSize: 'var(--text-md)', color: 'var(--color-text)' }}>모델별 사용량</h2>
              {data.by_model.length === 0 ? (
                <p className="ds-cell-muted" style={{ margin: 0 }}>클라우드 모델 사용 기록이 없습니다.</p>
              ) : (
                <div className="ds-table-wrap">
                  <table className="ds-table">
                    <caption className="sr-only">모델별 사용량</caption>
                    <thead>
                      <tr>
                        <th scope="col">제공자</th>
                        <th scope="col">모델</th>
                        <th scope="col" className="ds-cell-num">요청 수</th>
                        <th scope="col" className="ds-cell-num">입력 토큰</th>
                        <th scope="col" className="ds-cell-num">출력 토큰</th>
                        <th scope="col" className="ds-cell-num">추정 비용</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.by_model.map((row) => (
                        <tr key={`${row.provider}-${row.model_key}`}>
                          <td>{row.provider}</td>
                          <td style={{ fontWeight: 500 }}>{row.model_key}</td>
                          <td className="ds-cell-num">{row.requests.toLocaleString('en-US')}</td>
                          <td className="ds-cell-num">{formatTokens(row.input_tokens)}</td>
                          <td className="ds-cell-num">{formatTokens(row.output_tokens)}</td>
                          <td className="ds-cell-num">{formatCost(row.cost_usd)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>

            <section aria-label="사용자별 사용량" style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
              <h2 className="ds-section-title" style={{ fontSize: 'var(--text-md)', color: 'var(--color-text)' }}>사용자별 사용량</h2>
              {data.by_user.length === 0 ? (
                <p className="ds-cell-muted" style={{ margin: 0 }}>클라우드 모델 사용 기록이 없습니다.</p>
              ) : (
                <div className="ds-table-wrap">
                  <table className="ds-table">
                    <caption className="sr-only">사용자별 사용량</caption>
                    <thead>
                      <tr>
                        <th scope="col">사용자</th>
                        <th scope="col" className="ds-cell-num">요청 수</th>
                        <th scope="col" className="ds-cell-num">입력 토큰</th>
                        <th scope="col" className="ds-cell-num">출력 토큰</th>
                        <th scope="col" className="ds-cell-num">추정 비용</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.by_user.map((row) => (
                        <tr key={row.user_id}>
                          <td style={{ fontWeight: 500 }}>{row.username}</td>
                          <td className="ds-cell-num">{row.requests.toLocaleString('en-US')}</td>
                          <td className="ds-cell-num">{formatTokens(row.input_tokens)}</td>
                          <td className="ds-cell-num">{formatTokens(row.output_tokens)}</td>
                          <td className="ds-cell-num">{formatCost(row.cost_usd)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          </PageBody>
        </>
      )}
    </Page>
  )
}
