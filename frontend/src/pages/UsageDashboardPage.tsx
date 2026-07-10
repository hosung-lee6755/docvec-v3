import { DollarSign, Loader2, ShieldOff, BarChart3 } from 'lucide-react'
import { useUsageSummary } from '../hooks/useUsage'
import { useAuthStore } from '../store/authStore'

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
      <div style={{ textAlign: 'center', padding: 'var(--space-8)', color: 'var(--color-text-muted)' }}>
        <ShieldOff size={48} style={{ margin: '0 auto var(--space-4)', display: 'block', opacity: 0.4 }} />
        <p>관리자만 접근할 수 있습니다.</p>
      </div>
    )
  }

  return (
    <div>
      <style>{'@keyframes spin { to { transform: rotate(360deg) } }'}</style>

      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', marginBottom: 'var(--space-6)' }}>
        <h1 style={{ fontSize: 24, fontWeight: 700 }}>BYOK 사용량 대시보드</h1>
      </div>

      <p style={{ color: 'var(--color-text-muted)', marginBottom: 'var(--space-6)', fontSize: 13 }}>
        클라우드 LLM(OpenAI/Anthropic) 호출의 토큰 사용량과 추정 비용입니다. 로컬 모델(Qwen2.5)은 비용이 발생하지 않아 집계에서 제외됩니다.
        가격은 공개된 요율 기준 추정치이며 실제 청구서와 차이가 있을 수 있습니다.
      </p>

      {isLoading && (
        <div style={{ display: 'flex', justifyContent: 'center', padding: 'var(--space-8)' }}>
          <Loader2 size={24} style={{ animation: 'spin 1s linear infinite', color: 'var(--color-text-muted)' }} />
        </div>
      )}

      {isError && (
        <div style={{
          background: '#fef2f2', border: '1px solid #fecaca',
          borderRadius: 'var(--radius-md)', padding: 'var(--space-4)',
          color: '#dc2626', marginBottom: 'var(--space-4)',
        }}>
          사용량 데이터를 불러오지 못했습니다.
        </div>
      )}

      {!isLoading && !isError && data && (
        <>
          <div style={{
            display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
            gap: 'var(--space-4)', marginBottom: 'var(--space-8)',
          }}>
            <SummaryCard icon={<BarChart3 size={20} />} label="총 요청 수" value={data.summary.total_requests.toLocaleString('en-US')} />
            <SummaryCard icon={<BarChart3 size={20} />} label="입력 토큰" value={formatTokens(data.summary.total_input_tokens)} />
            <SummaryCard icon={<BarChart3 size={20} />} label="출력 토큰" value={formatTokens(data.summary.total_output_tokens)} />
            <SummaryCard icon={<DollarSign size={20} />} label="추정 비용" value={formatCost(data.summary.total_cost_usd)} highlight />
          </div>

          <h2 style={{ fontSize: 18, fontWeight: 600, marginBottom: 'var(--space-3)' }}>모델별 사용량</h2>
          {data.by_model.length === 0 ? (
            <p style={{ color: 'var(--color-text-muted)', marginBottom: 'var(--space-8)' }}>클라우드 모델 사용 기록이 없습니다.</p>
          ) : (
            <div className="krds-table-wrap" style={{ marginBottom: 'var(--space-8)' }}>
              <table className="tbl col data">
                <caption>모델별 사용량</caption>
                <thead>
                  <tr>
                    <th scope="col">제공자</th>
                    <th scope="col">모델</th>
                    <th scope="col">요청 수</th>
                    <th scope="col">입력 토큰</th>
                    <th scope="col">출력 토큰</th>
                    <th scope="col">추정 비용</th>
                  </tr>
                </thead>
                <tbody>
                  {data.by_model.map((row) => (
                    <tr key={`${row.provider}-${row.model_key}`}>
                      <td>{row.provider}</td>
                      <td style={{ fontWeight: 500 }}>{row.model_key}</td>
                      <td>{row.requests.toLocaleString('en-US')}</td>
                      <td>{formatTokens(row.input_tokens)}</td>
                      <td>{formatTokens(row.output_tokens)}</td>
                      <td>{formatCost(row.cost_usd)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <h2 style={{ fontSize: 18, fontWeight: 600, marginBottom: 'var(--space-3)' }}>사용자별 사용량</h2>
          {data.by_user.length === 0 ? (
            <p style={{ color: 'var(--color-text-muted)' }}>클라우드 모델 사용 기록이 없습니다.</p>
          ) : (
            <div className="krds-table-wrap">
              <table className="tbl col data">
                <caption>사용자별 사용량</caption>
                <thead>
                  <tr>
                    <th scope="col">사용자</th>
                    <th scope="col">요청 수</th>
                    <th scope="col">입력 토큰</th>
                    <th scope="col">출력 토큰</th>
                    <th scope="col">추정 비용</th>
                  </tr>
                </thead>
                <tbody>
                  {data.by_user.map((row) => (
                    <tr key={row.user_id}>
                      <td style={{ fontWeight: 500 }}>{row.username}</td>
                      <td>{row.requests.toLocaleString('en-US')}</td>
                      <td>{formatTokens(row.input_tokens)}</td>
                      <td>{formatTokens(row.output_tokens)}</td>
                      <td>{formatCost(row.cost_usd)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  )
}

function SummaryCard({ icon, label, value, highlight }: { icon: React.ReactNode; label: string; value: string; highlight?: boolean }) {
  return (
    <div style={{
      border: '1px solid var(--color-border)', borderRadius: 'var(--radius-md)',
      padding: 'var(--space-4)', background: highlight ? 'var(--color-primary-subtle, #eff6ff)' : 'var(--color-surface)',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', color: 'var(--color-text-muted)', marginBottom: 'var(--space-2)' }}>
        {icon}
        <span style={{ fontSize: 13 }}>{label}</span>
      </div>
      <div style={{ fontSize: 22, fontWeight: 700 }}>{value}</div>
    </div>
  )
}
