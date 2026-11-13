// 실패: 처리에 실패한 문서를 원인별로 묶어 보여 주고, 고른 문서를 실패한 단계부터 다시 처리한다.
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { CheckCircle2, RotateCcw } from 'lucide-react'
import { useFailureQueue, type FailureQueueItem } from '../hooks/useDocumentQueues'
import { useBatchReprocessDocuments, type BatchReprocessItemResult } from '../hooks/useDocuments'
import { explainFailure } from '../lib/apiError'
import { failureCauseHeadline, formatElapsed, groupFailureCauses } from '../lib/documentQueues'
import { getBlockMeta } from '../lib/workflowBlocks'
import {
  Alert, Badge, Button, EmptyState, ErrorAlert, FilterChip, Page, PageBody, PageHeader, Spinner, Stat, StatStrip,
  Toolbar, buttonClass,
} from '../components/ui'

// 이 횟수 이상 실패하면 같은 설정으로 다시 처리해도 또 실패할 가능성이 높다고 알린다
const REPEATED_FAILURE_COUNT = 2

export default function FailureQueuePage() {
  const { data, isLoading, isError, error, refetch } = useFailureQueue()
  const reprocess = useBatchReprocessDocuments()
  const [cause, setCause] = useState<string | null>(null)
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set())
  const [results, setResults] = useState<BatchReprocessItemResult[] | null>(null)

  const items = useMemo(() => data?.items ?? [], [data])
  const causes = useMemo(() => groupFailureCauses(items), [items])
  const visible = cause ? items.filter((item) => failureCauseHeadline(item.error_message) === cause) : items
  const retryable = visible.filter((item) => item.can_retry)
  const repeatedCount = items.filter((item) => item.failure_count >= REPEATED_FAILURE_COUNT).length
  const selectedIds = retryable.filter((item) => selected.has(item.document_id)).map((item) => item.document_id)

  const toggleOne = (id: string) => setSelected((current) => {
    const next = new Set(current)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    return next
  })
  const toggleAll = () => setSelected(
    selectedIds.length === retryable.length ? new Set() : new Set(retryable.map((item) => item.document_id)),
  )
  const runReprocess = (ids: string[]) => {
    setResults(null)
    reprocess.mutate(ids, {
      onSuccess: (response) => {
        setResults(response.results)
        setSelected(new Set())
        refetch()
      },
    })
  }

  return (
    <Page>
      <PageHeader
        title="실패"
        subtitle="처리에 실패한 문서입니다. 원인을 확인하고, 고친 뒤 실패한 단계부터 다시 처리하세요."
      />
      <StatStrip label="실패 요약">
        <Stat label="실패 문서" value={data?.total ?? 0} tone={(data?.total ?? 0) > 0 ? 'danger' : 'default'} />
        <Stat label="바로 다시 처리 가능" value={items.filter((item) => item.can_retry).length} />
        <Stat
          label={`${REPEATED_FAILURE_COUNT}번 이상 실패`} value={repeatedCount}
          tone={repeatedCount > 0 ? 'warning' : 'default'}
          hint={repeatedCount > 0 ? '설정이나 원본을 먼저 확인하세요' : undefined}
        />
        <Stat label="원인 종류" value={causes.length} />
      </StatStrip>

      {causes.length > 1 && (
        <Toolbar label="원인별 거르기">
          <FilterChip isActive={cause === null} onClick={() => setCause(null)}>전체 {items.length}</FilterChip>
          {causes.map((group) => (
            <FilterChip
              key={group.cause} isActive={cause === group.cause}
              onClick={() => setCause(cause === group.cause ? null : group.cause)}
            >
              {group.cause} {group.count}
            </FilterChip>
          ))}
        </Toolbar>
      )}

      <PageBody>
        {isError && <ErrorAlert error={error} message="실패 목록을 불러오지 못했습니다." onRetry={() => refetch()} />}
        {reprocess.isError && <ErrorAlert error={reprocess.error} message="다시 처리를 시작하지 못했습니다." />}
        {results && <ReprocessSummary results={results} items={items} />}

        {retryable.length > 0 && (
          <div style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'center', flexWrap: 'wrap' }}>
            <Button
              size="sm" variant="primary" icon={<RotateCcw size={14} aria-hidden="true" />}
              disabled={!selectedIds.length || reprocess.isPending}
              onClick={() => runReprocess(selectedIds)}
            >
              {selectedIds.length ? `고른 ${selectedIds.length}건 다시 처리` : '다시 처리할 문서를 고르세요'}
            </Button>
            <span className="ds-cell-muted">실패한 단계부터 이어서 처리합니다. 앞 단계 결과는 그대로 씁니다.</span>
          </div>
        )}

        {isLoading && <Spinner />}
        {!isLoading && !isError && visible.length === 0 && (
          <EmptyState
            icon={<CheckCircle2 size={28} aria-hidden="true" />}
            title="실패한 문서가 없습니다"
            description="처리 중 오류가 나면 실패한 단계와 원인이 여기에 모입니다."
          />
        )}
        {visible.length > 0 && (
          <div className="ds-table-wrap">
            <table className="ds-table">
              <caption className="sr-only">실패한 문서</caption>
              <thead>
                <tr>
                  <th scope="col" style={{ width: 32 }}>
                    <input
                      type="checkbox" aria-label="다시 처리할 수 있는 문서 모두 고르기"
                      checked={retryable.length > 0 && selectedIds.length === retryable.length}
                      disabled={!retryable.length}
                      onChange={toggleAll}
                    />
                  </th>
                  <th scope="col">문서</th>
                  <th scope="col">실패한 단계</th>
                  <th scope="col">원인</th>
                  <th scope="col">실패</th>
                  <th scope="col"><span className="sr-only">작업</span></th>
                </tr>
              </thead>
              <tbody>
                {visible.map((item) => (
                  <FailureRow
                    key={item.document_id}
                    item={item}
                    isSelected={selected.has(item.document_id)}
                    isBusy={reprocess.isPending}
                    onToggle={() => toggleOne(item.document_id)}
                    onRetry={() => runReprocess([item.document_id])}
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

function FailureRow({ item, isSelected, isBusy, onToggle, onRetry }: {
  item: FailureQueueItem
  isSelected: boolean
  isBusy: boolean
  onToggle: () => void
  onRetry: () => void
}) {
  const isRepeated = item.failure_count >= REPEATED_FAILURE_COUNT
  return (
    <tr>
      <td>
        <input
          type="checkbox" aria-label={`${item.filename} 고르기`}
          checked={isSelected} disabled={!item.can_retry} onChange={onToggle}
        />
      </td>
      <td>
        <Link to={`/documents/${item.document_id}`} className="ds-link-btn">{item.filename}</Link>
        <span className="ds-cell-sub">{item.collection_name ?? '컬렉션 없음'}</span>
      </td>
      <td style={{ whiteSpace: 'nowrap' }}>
        {item.failed_block_type ? getBlockMeta(item.failed_block_type).label : <span className="ds-cell-muted">기록 없음</span>}
      </td>
      <td style={{ maxWidth: 420 }}>
        <span style={{ fontSize: 'var(--text-sm)' }}>{explainFailure(item.error_message)}</span>
      </td>
      <td style={{ whiteSpace: 'nowrap' }}>
        {isRepeated ? <Badge tone="danger">{item.failure_count}번째</Badge> : <span>{item.failure_count}번째</span>}
        <span className="ds-cell-sub">{formatElapsed(item.failed_at)}</span>
      </td>
      <td>
        <div style={{ display: 'flex', gap: 'var(--space-2)', justifyContent: 'flex-end', flexWrap: 'wrap' }}>
          <Link to={`/documents/${item.document_id}?tab=history`} className={buttonClass('secondary', 'sm')}>처리 이력</Link>
          <Button
            size="sm" variant="ghost" disabled={!item.can_retry || isBusy} onClick={onRetry}
            title={item.can_retry ? undefined : '실패한 단계가 기록되지 않아 이어서 처리할 수 없습니다. 문서 상세에서 전체 재처리를 하세요.'}
          >
            다시 처리
          </Button>
        </div>
      </td>
    </tr>
  )
}

function ReprocessSummary({ results, items }: { results: BatchReprocessItemResult[]; items: FailureQueueItem[] }) {
  const queued = results.filter((r) => r.status === 'queued').length
  const problems = results.filter((r) => r.status !== 'queued')
  const nameOf = (id: string) => items.find((item) => item.document_id === id)?.filename ?? id
  return (
    <Alert tone={problems.length ? 'warning' : 'success'}>
      <div>{queued}건을 다시 처리하기 시작했습니다.{problems.length > 0 && ` ${problems.length}건은 시작하지 못했습니다.`}</div>
      {problems.map((r) => (
        <div key={r.id} className="ds-cell-sub">{nameOf(r.id)}: {r.detail ?? '이유가 기록되지 않았습니다.'}</div>
      ))}
    </Alert>
  )
}
