// 검토 대기: 처리가 검토 단계에서 멈춘 문서와 멈춘 이유를 모아 보여 주고, 바로 승인하거나 반려한다.
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { CheckCircle2 } from 'lucide-react'
import {
  useApproveReview, useRejectReview, useReviewQueue,
  type ReviewQueueItem, type ReviewReason,
} from '../hooks/useDocumentQueues'
import {
  PII_TYPE_LABELS, QUALITY_CATEGORY_LABELS, QUALITY_STATUS_LABELS, REVIEW_REASON_LABELS,
  formatElapsed, isStale,
} from '../lib/documentQueues'
import {
  Badge, Button, EmptyState, ErrorAlert, Page, PageBody, PageHeader, Spinner, Stat, StatStrip, buttonClass,
} from '../components/ui'

// 한 줄에 보여 줄 품질 경고 수. 나머지는 "외 N건"으로 줄인다
const VISIBLE_WARNINGS = 2

type ReasonFilter = ReviewReason | 'all'

export default function ReviewQueuePage() {
  const { data, isLoading, isError, error, refetch } = useReviewQueue()
  const approve = useApproveReview()
  const reject = useRejectReview()
  const [filter, setFilter] = useState<ReasonFilter>('all')

  const items = data?.items ?? []
  const visible = filter === 'all' ? items : items.filter((item) => item.reasons.includes(filter))
  const staleCount = items.filter((item) => isStale(item.waiting_since)).length
  const toggle = (next: ReasonFilter) => setFilter((current) => (current === next ? 'all' : next))

  const handleApprove = (item: ReviewQueueItem) => {
    if (!item.run_id) return
    if (!window.confirm(`"${item.filename}"을(를) 승인하고 남은 처리를 이어서 진행할까요?`)) return
    approve.mutate(item.run_id)
  }
  const handleReject = (item: ReviewQueueItem) => {
    if (!item.run_id) return
    if (!window.confirm(`"${item.filename}"을(를) 반려할까요? 처리가 멈추고 문서는 실패 목록으로 옮겨집니다.`)) return
    reject.mutate(item.run_id)
  }

  return (
    <Page>
      <PageHeader
        title="검토 대기"
        subtitle="처리 도중 사람의 확인이 필요해 멈춘 문서입니다. 오래 기다린 문서가 위에 옵니다."
      />
      <StatStrip label="검토 대기 요약">
        <Stat label="전체" value={data?.total ?? 0} onClick={() => setFilter('all')} isActive={filter === 'all'} />
        <Stat
          label={REVIEW_REASON_LABELS.quality} value={data?.counts.quality ?? 0} tone="warning"
          onClick={() => toggle('quality')} isActive={filter === 'quality'}
        />
        <Stat
          label={REVIEW_REASON_LABELS.pii} value={data?.counts.pii ?? 0} tone="warning"
          onClick={() => toggle('pii')} isActive={filter === 'pii'}
        />
        <Stat label="하루 넘게 대기" value={staleCount} tone={staleCount > 0 ? 'danger' : 'default'} />
      </StatStrip>

      <PageBody>
        {isError && <ErrorAlert error={error} message="검토 대기 목록을 불러오지 못했습니다." onRetry={() => refetch()} />}
        {approve.isError && <ErrorAlert error={approve.error} message="승인하지 못했습니다." />}
        {reject.isError && <ErrorAlert error={reject.error} message="반려하지 못했습니다." />}
        {data && data.total > items.length && (
          <p className="ds-cell-muted" style={{ margin: 0 }}>
            전체 {data.total}건 중 오래 기다린 {items.length}건을 보여 줍니다.
          </p>
        )}

        {isLoading && <Spinner />}
        {!isLoading && !isError && visible.length === 0 && (
          <EmptyState
            icon={<CheckCircle2 size={28} aria-hidden="true" />}
            title={filter === 'all' ? '검토를 기다리는 문서가 없습니다' : `${REVIEW_REASON_LABELS[filter]} 문서가 없습니다`}
            description="처리 중 품질 경고가 나거나 개인정보 승인이 필요하면 여기에 모입니다."
          />
        )}
        {visible.length > 0 && (
          <div className="ds-table-wrap">
            <table className="ds-table">
              <caption className="sr-only">검토 대기 문서</caption>
              <thead>
                <tr>
                  <th scope="col">문서</th>
                  <th scope="col">멈춘 이유</th>
                  <th scope="col">대기</th>
                  <th scope="col"><span className="sr-only">작업</span></th>
                </tr>
              </thead>
              <tbody>
                {visible.map((item) => (
                  <ReviewRow
                    key={item.document_id}
                    item={item}
                    isBusy={approve.isPending || reject.isPending}
                    onApprove={() => handleApprove(item)}
                    onReject={() => handleReject(item)}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </PageBody>
    </Page>
  )
}

function ReviewRow({ item, isBusy, onApprove, onReject }: {
  item: ReviewQueueItem
  isBusy: boolean
  onApprove: () => void
  onReject: () => void
}) {
  const reviewTab = item.reasons.includes('pii') && !item.reasons.includes('quality') ? 'pii' : 'quality'
  const stale = isStale(item.waiting_since)
  return (
    <tr>
      <td>
        <Link to={`/documents/${item.document_id}`} className="ds-link-btn">{item.filename}</Link>
        <span className="ds-cell-sub">{item.collection_name ?? '컬렉션 없음'}</span>
      </td>
      <td>
        <ReviewReasons item={item} />
      </td>
      <td style={{ whiteSpace: 'nowrap' }}>
        {stale ? <Badge tone="danger">{formatElapsed(item.waiting_since)}</Badge> : formatElapsed(item.waiting_since)}
      </td>
      <td>
        <div style={{ display: 'flex', gap: 'var(--space-2)', justifyContent: 'flex-end', flexWrap: 'wrap' }}>
          <Link to={`/documents/${item.document_id}?tab=${reviewTab}`} className={buttonClass('secondary', 'sm')}>
            검토하기
          </Link>
          <Button size="sm" variant="primary" disabled={!item.run_id || isBusy} onClick={onApprove}>승인하고 계속</Button>
          <Button size="sm" variant="ghost" disabled={!item.run_id || isBusy} onClick={onReject}>반려</Button>
        </div>
      </td>
    </tr>
  )
}

function ReviewReasons({ item }: { item: ReviewQueueItem }) {
  const categories = [...new Set(item.warning_categories.filter((c): c is string => !!c))]
  const hiddenWarnings = item.warnings.length - VISIBLE_WARNINGS
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <div style={{ display: 'flex', gap: 'var(--space-1)', flexWrap: 'wrap', alignItems: 'center' }}>
        {item.reasons.map((reason) => (
          <Badge key={reason} tone={reason === 'unknown' ? 'neutral' : 'warning'}>{REVIEW_REASON_LABELS[reason]}</Badge>
        ))}
        {item.quality_status && (
          <span className="ds-cell-muted">
            {QUALITY_STATUS_LABELS[item.quality_status] ?? item.quality_status}
            {item.overall_score != null && ` · 품질 점수 ${item.overall_score.toFixed(1)}점`}
          </span>
        )}
        {categories.map((c) => <Badge key={c} tone="outline">{QUALITY_CATEGORY_LABELS[c] ?? c}</Badge>)}
      </div>
      {item.warnings.slice(0, VISIBLE_WARNINGS).map((warning, i) => (
        <span key={i} className="ds-cell-sub">{warning}</span>
      ))}
      {hiddenWarnings > 0 && <span className="ds-cell-sub">외 경고 {hiddenWarnings}건</span>}
      {item.pii_pending_count > 0 && (
        <span className="ds-cell-sub">
          개인정보 {item.pii_pending_count}건 승인 대기
          {item.pii_entity_types.length > 0 && ` (${item.pii_entity_types.map((t) => PII_TYPE_LABELS[t] ?? t).join(', ')})`}
        </span>
      )}
      {item.reasons.includes('unknown') && (
        <span className="ds-cell-sub">멈춘 이유가 기록되지 않았습니다. 문서 상세의 처리 이력에서 멈춘 단계를 확인하세요.</span>
      )}
    </div>
  )
}
