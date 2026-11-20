// 검토 대기: 처리가 검토 단계에서 멈춘 문서와 멈춘 이유를 모아 보여 주고, 바로 승인하거나 반려한다.
import { Fragment, useState } from 'react'
import { Link } from 'react-router-dom'
import { CheckCircle2 } from 'lucide-react'
import {
  useApproveReview, useBulkApproveReview, useBulkRejectReview, useRejectReview, useReviewQueue,
  type BulkReviewResult, type ReviewQueueItem, type ReviewReason,
} from '../hooks/useDocumentQueues'
import PiiDetectionsTab from '../components/document-detail/PiiDetectionsTab'
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
  const bulkApprove = useBulkApproveReview()
  const bulkReject = useBulkRejectReview()
  const [filter, setFilter] = useState<ReasonFilter>('all')
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [bulkResult, setBulkResult] = useState<string | null>(null)

  const items = data?.items ?? []
  const visible = filter === 'all' ? items : items.filter((item) => item.reasons.includes(filter))
  const staleCount = items.filter((item) => isStale(item.waiting_since)).length
  const toggle = (next: ReasonFilter) => setFilter((current) => (current === next ? 'all' : next))
  const isBusy = approve.isPending || reject.isPending || bulkApprove.isPending || bulkReject.isPending

  // 지금 보이는 문서 중 고른 것만 대상으로 한다. 필터를 바꾸거나 처리가 끝나 목록에서 빠진 문서는 세지 않는다
  const actionable = visible.filter((item) => item.run_id)
  const selected = actionable.filter((item) => selectedIds.has(item.document_id))
  const isAllSelected = selected.length > 0 && selected.length === actionable.length
  const toggleAll = () => setSelectedIds(isAllSelected ? new Set() : new Set(actionable.map((item) => item.document_id)))
  const toggleSelect = (documentId: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(documentId)) next.delete(documentId)
      else next.add(documentId)
      return next
    })
  }

  const runBulk = (targets: ReviewQueueItem[], shouldApprove: boolean, scope: string) => {
    if (targets.length === 0) return
    const message = shouldApprove
      ? `${scope} 문서 ${targets.length}건을 승인하고 남은 처리를 이어서 진행할까요?`
      : `${scope} 문서 ${targets.length}건을 반려할까요? 처리가 멈추고 문서는 실패 목록으로 옮겨집니다.`
    if (!window.confirm(message)) return
    const mutation = shouldApprove ? bulkApprove : bulkReject
    const verb = shouldApprove ? '승인' : '반려'
    setBulkResult(null)
    mutation.mutate(targets.map((item) => item.run_id as string), {
      onSuccess: ({ succeeded, failed }: BulkReviewResult) => {
        setSelectedIds(new Set())
        setBulkResult(failed > 0
          ? `${succeeded}건을 ${verb}했고 ${failed}건은 ${verb}하지 못했습니다. 남은 문서를 다시 시도해 주세요.`
          : `${succeeded}건을 ${verb}했습니다.`)
      },
    })
  }

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
        {bulkResult && <p className="ds-cell-muted" role="status" style={{ margin: 0 }}>{bulkResult}</p>}
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
          <div style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'center', flexWrap: 'wrap' }}>
            <span className="ds-cell-muted" style={{ marginRight: 'auto' }}>
              {selected.length > 0 ? `${selected.length}건 선택` : '문서를 골라 한꺼번에 승인하거나 반려할 수 있습니다.'}
            </span>
            <Button size="sm" variant="primary" disabled={isBusy || selected.length === 0} onClick={() => runBulk(selected, true, '선택한')}>
              선택 승인하고 계속
            </Button>
            <Button size="sm" variant="ghost" disabled={isBusy || selected.length === 0} onClick={() => runBulk(selected, false, '선택한')}>
              선택 반려
            </Button>
            <Button size="sm" variant="secondary" disabled={isBusy || actionable.length === 0} onClick={() => runBulk(actionable, true, '목록의')}>
              전체 승인하고 계속
            </Button>
          </div>
        )}
        {visible.length > 0 && (
          <div className="ds-table-wrap">
            <table className="ds-table">
              <caption className="sr-only">검토 대기 문서</caption>
              <thead>
                <tr>
                  <th scope="col" className="ds-cell-check">
                    <input type="checkbox" aria-label="검토 대기 문서 전체 선택" checked={isAllSelected} onChange={toggleAll} />
                  </th>
                  <th scope="col">문서</th>
                  <th scope="col">멈춘 이유</th>
                  <th scope="col">대기</th>
                  <th scope="col"><span className="sr-only">작업</span></th>
                </tr>
              </thead>
              <tbody>
                {visible.map((item) => (
                  <Fragment key={item.document_id}>
                    <ReviewRow
                      item={item}
                      isBusy={isBusy}
                      isSelected={selectedIds.has(item.document_id)}
                      isExpanded={expandedId === item.document_id}
                      onToggleSelect={() => toggleSelect(item.document_id)}
                      onToggleExpand={() => setExpandedId((cur) => (cur === item.document_id ? null : item.document_id))}
                      onApprove={() => handleApprove(item)}
                      onReject={() => handleReject(item)}
                    />
                    {expandedId === item.document_id && (
                      <tr>
                        <td colSpan={5} style={{ background: 'var(--color-surface-subtle)' }}>
                          <PiiDetectionsTab documentId={item.document_id} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </PageBody>
    </Page>
  )
}

function ReviewRow({
  item, isBusy, isSelected, isExpanded, onToggleSelect, onToggleExpand, onApprove, onReject,
}: {
  item: ReviewQueueItem
  isBusy: boolean
  isSelected: boolean
  isExpanded: boolean
  onToggleSelect: () => void
  onToggleExpand: () => void
  onApprove: () => void
  onReject: () => void
}) {
  const reviewTab = item.reasons.includes('pii') && !item.reasons.includes('quality') ? 'pii' : 'quality'
  const stale = isStale(item.waiting_since)
  return (
    <tr className={isSelected ? 'is-selected' : undefined}>
      <td className="ds-cell-check">
        <input
          type="checkbox"
          aria-label={`${item.filename} 선택`}
          checked={isSelected}
          disabled={!item.run_id}
          onChange={onToggleSelect}
        />
      </td>
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
          {item.reasons.includes('pii') && (
            <Button size="sm" variant="ghost" onClick={onToggleExpand} aria-expanded={isExpanded}>
              {isExpanded ? '민감정보 접기' : '민감정보 보기'}
            </Button>
          )}
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
