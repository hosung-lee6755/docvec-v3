import { useEffect, useState } from 'react'
import { useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { Upload, Trash2, X, RefreshCw } from 'lucide-react'
import { useDocuments, useDeleteDocument, useBatchDeleteDocuments, useBatchReprocessDocuments, type DocumentLifecycleFilter, type DocumentQualityFilter, type DocumentSortBy, type SortOrder } from '../hooks/useDocuments'
import { useCollections } from '../hooks/useCollections'
import { PROCESSING_STATUSES, STATUS_FILTER_OPTIONS, statusFilterValue } from '../lib/documentStatus'
import { LIFECYCLE_FILTER_LABELS } from '../lib/documentLifecycle'
import { DocumentsTable } from '../components/documents/DocumentsTable'
import { UploadModal } from '../components/documents/UploadModal'
import { Alert, BulkActionBar, Button, Card, EmptyState, ErrorAlert, IconButton, Page, PageHeader, SearchInput, Select, Spinner, Stat, StatStrip, Toolbar } from '../components/ui'
import '../styles/screens/documents.css'

// v3 마일스톤 6: 최근 처리 결과의 품질로 문서를 거른다
const QUALITY_FILTER_LABELS: Record<DocumentQualityFilter, string> = {
  low_ocr: 'OCR 신뢰도 낮은 쪽 있음',
  warning: '경고·부분 실패',
  failure: '처리 실패',
}

// 요약 띠의 '검토 대기', '실패' 칸은 사이드바 링크와 같은 상태 값으로 거른다.
const REVIEW_WAITING_STATUS = statusFilterValue('WAITING_REVIEW')
const FAILED_STATUS = 'FAILED'

export default function DocumentsPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const { projectId } = useParams<{ projectId?: string }>()
  const [searchParams, setSearchParams] = useSearchParams()
  const [showUploadModal, setShowUploadModal] = useState(false)
  const [filterCollectionId, setFilterCollectionId] = useState(() => searchParams.get('collection') ?? '')
  const [filterStatus, setFilterStatus] = useState('')
  const [filterQuality, setFilterQuality] = useState<DocumentQualityFilter | ''>('')
  const [filterLifecycle, setFilterLifecycle] = useState<DocumentLifecycleFilter | ''>('')
  const [uploadNotice, setUploadNotice] = useState<string | null>(null)
  const [filenameInput, setFilenameInput] = useState('')
  const [filenameFilter, setFilenameFilter] = useState('')
  const [sortBy, setSortBy] = useState<DocumentSortBy>('created_at')
  const [order, setOrder] = useState<SortOrder>('desc')
  const [page, setPage] = useState(1)
  const [limit, setLimit] = useState(20)

  useEffect(() => {
    const id = setTimeout(() => setFilenameFilter(filenameInput.trim()), 300)
    return () => clearTimeout(id)
  }, [filenameInput])

  // Deep-link support: ?collection=<id> (e.g. clicking a collection name in the
  // collections list). Always sync — including clearing back to '' when the
  // param is absent — otherwise navigating from a collection-filtered link to
  // the plain "문서" nav item leaves the previous filter stuck (component
  // doesn't remount, only searchParams changes) and the list silently stays
  // empty/filtered with no visible cause.
  useEffect(() => {
    setFilterCollectionId(searchParams.get('collection') ?? '')
  }, [searchParams])

  // Deep-link support: ?status=<status> (e.g. the "검토 대기" nav link) — same
  // always-sync rationale as the collection filter above.
  useEffect(() => {
    setFilterStatus(statusFilterValue(searchParams.get('status') ?? ''))
  }, [searchParams])

  useEffect(() => {
    if ((location.state as { openUpload?: boolean } | null)?.openUpload) {
      setShowUploadModal(true)
      navigate(location.pathname, { replace: true, state: null })
    }
  }, [location, navigate])

  const { data, isLoading, isError, error, refetch } = useDocuments({
    page,
    limit,
    collectionId: filterCollectionId,
    projectId,
    status: filterStatus,
    filename: filenameFilter,
    quality: filterQuality,
    lifecycle: filterLifecycle,
    sortBy,
    order,
  })
  const totalPages = Math.max(1, Math.ceil((data?.total ?? 0) / limit))

  // 필터/정렬/표시건수가 바뀌면 이전 페이지 번호가 새 결과 범위를 벗어날 수
  // 있어(예: 3페이지 보다가 필터링하면 결과가 1페이지뿐) 1페이지로 되돌린다.
  useEffect(() => {
    setPage(1)
  }, [filterCollectionId, filterStatus, filterQuality, filterLifecycle, filenameFilter, sortBy, order, limit])
  const deleteDoc = useDeleteDocument()
  const batchDelete = useBatchDeleteDocuments()
  const batchReprocess = useBatchReprocessDocuments()
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null)
  const [confirmBulkDelete, setConfirmBulkDelete] = useState(false)
  const [reprocessSummary, setReprocessSummary] = useState<string | null>(null)
  const { data: collectionsData } = useCollections(projectId)

  const items = data?.items ?? []
  // 요약 띠는 지금 받은 목록(이 페이지)으로만 센다. 새 API를 부르지 않는다.
  const processingCount = items.filter((d) => PROCESSING_STATUSES.includes(d.status)).length
  const waitingCount = items.filter((d) => REVIEW_WAITING_STATUS.split(',').includes(d.status)).length
  const failedCount = items.filter((d) => d.status === FAILED_STATUS).length

  const toggleSort = (column: DocumentSortBy) => {
    if (sortBy === column) {
      setOrder((o) => (o === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortBy(column)
      setOrder('asc')
    }
  }

  // 상태·컬렉션 필터는 URL이 원본이다. 화면 안에서 바꿀 때도 URL을 고쳐야 사이드바 강조와
  // 새로고침 결과가 지금 보이는 목록과 어긋나지 않는다. 상태값은 위 effect가 URL에서 다시 읽는다.
  const setUrlFilter = (key: 'status' | 'collection', value: string) => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      if (value) next.set(key, value)
      else next.delete(key)
      return next
    }, { replace: true })
  }

  const hasActiveFilters = !!(filterCollectionId || filterStatus || filterQuality || filterLifecycle || filenameFilter)
  const clearFilters = () => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      next.delete('status')
      next.delete('collection')
      return next
    }, { replace: true })
    setFilterQuality('')
    setFilterLifecycle('')
    setFilenameInput('')
    setFilenameFilter('')
  }

  const toggleSelect = (id: string) =>
    setSelectedIds((prev) => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })

  const toggleAll = () =>
    setSelectedIds((prev) =>
      prev.size > 0 && prev.size === (data?.items.length ?? 0)
        ? new Set()
        : new Set(data?.items.map((d) => d.id) ?? [])
    )

  const clearSelection = () => {
    setSelectedIds(new Set())
    setConfirmBulkDelete(false)
  }

  const handleBulkReprocess = () => {
    const ids = [...selectedIds]
    batchReprocess.mutate(ids, {
      onSuccess: (result) => {
        const queued = result.results.filter((r) => r.status === 'queued').length
        const skipped = result.results.filter((r) => r.status === 'skipped').length
        const failed = result.results.filter((r) => r.status === 'failed').length
        setReprocessSummary(
          `재처리 시작 ${queued}건` +
          (skipped ? `, 건너뜀 ${skipped}건(실패 상태 아님)` : '') +
          (failed ? `, 실패 ${failed}건` : ''),
        )
        setSelectedIds(new Set())
      },
    })
  }

  const handleBulkDelete = () => batchDelete.mutate([...selectedIds], {
    onSuccess: () => { setSelectedIds(new Set()); setConfirmBulkDelete(false) },
  })

  return (
    <Page>
      <PageHeader
        title="문서"
        actions={
          <Button variant="primary" icon={<Upload size={14} />} onClick={() => setShowUploadModal(true)}>
            문서 업로드
          </Button>
        }
      />

      <StatStrip>
        <Stat
          label="전체"
          value={data?.total ?? 0}
          isActive={filterStatus === ''}
          onClick={() => setUrlFilter('status', '')}
        />
        <Stat label="처리 중" value={processingCount} hint="이 페이지" />
        <Stat
          label="검토 대기"
          value={waitingCount}
          hint="이 페이지"
          tone={waitingCount > 0 ? 'warning' : 'default'}
          isActive={filterStatus === REVIEW_WAITING_STATUS}
          onClick={() => setUrlFilter('status', REVIEW_WAITING_STATUS)}
        />
        <Stat
          label="실패"
          value={failedCount}
          hint="이 페이지"
          tone={failedCount > 0 ? 'danger' : 'default'}
          isActive={filterStatus === FAILED_STATUS}
          onClick={() => setUrlFilter('status', FAILED_STATUS)}
        />
      </StatStrip>

      <Toolbar label="문서 거르기" meta={`${data?.total ?? 0}건`}>
        <SearchInput
          label="파일명 검색"
          placeholder="파일명 검색..."
          value={filenameInput}
          onChange={(e) => setFilenameInput(e.target.value)}
        />
        <Select
          controlSize="sm"
          aria-label="컬렉션으로 거르기"
          value={filterCollectionId}
          onChange={(e) => setUrlFilter('collection', e.target.value)}
          style={{ width: 180 }}
        >
          <option value="">전체 컬렉션</option>
          {collectionsData?.items.map((c) => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </Select>

        <Select
          controlSize="sm"
          aria-label="상태로 거르기"
          value={filterStatus}
          onChange={(e) => setUrlFilter('status', e.target.value)}
          style={{ width: 140 }}
        >
          <option value="">전체 상태</option>
          {STATUS_FILTER_OPTIONS.map(({ value, label }) => (
            <option key={value} value={value}>{label}</option>
          ))}
        </Select>

        <Select
          controlSize="sm"
          value={filterQuality}
          onChange={(e) => setFilterQuality(e.target.value as DocumentQualityFilter | '')}
          style={{ width: 170 }}
          aria-label="처리 품질로 거르기"
        >
          <option value="">전체 품질</option>
          {Object.entries(QUALITY_FILTER_LABELS).map(([value, label]) => (
            <option key={value} value={value}>{label}</option>
          ))}
        </Select>

        <Select
          controlSize="sm"
          value={filterLifecycle}
          onChange={(e) => setFilterLifecycle(e.target.value as DocumentLifecycleFilter | '')}
          style={{ width: 200 }}
          aria-label="버전·보관 상태로 거르기"
        >
          <option value="">기본(이전 버전 숨김)</option>
          {Object.entries(LIFECYCLE_FILTER_LABELS).map(([value, label]) => (
            <option key={value} value={value}>{label}</option>
          ))}
        </Select>

        {hasActiveFilters && (
          <Button variant="ghost" size="sm" icon={<X size={14} />} onClick={clearFilters}>
            필터 초기화
          </Button>
        )}

        <Select
          controlSize="sm"
          aria-label="표시 건수"
          value={limit}
          onChange={(e) => setLimit(Number(e.target.value))}
          style={{ width: 110 }}
        >
          {[10, 20, 50, 100, 200].map((n) => (
            <option key={n} value={n}>{n}건씩 보기</option>
          ))}
        </Select>
      </Toolbar>

      <BulkActionBar count={selectedIds.size} onClear={clearSelection}>
        {confirmBulkDelete ? (
          <>
            <span>정말 삭제하시겠습니까?</span>
            <button type="button" disabled={batchDelete.isPending} onClick={handleBulkDelete}>확인</button>
            <button type="button" onClick={() => setConfirmBulkDelete(false)}>취소</button>
          </>
        ) : (
          <>
            <button type="button" disabled={batchReprocess.isPending} onClick={handleBulkReprocess}>
              <RefreshCw size={12} aria-hidden="true" /> {batchReprocess.isPending ? '재처리 요청 중...' : '선택 재처리'}
            </button>
            <button type="button" className="is-danger" onClick={() => setConfirmBulkDelete(true)}>
              <Trash2 size={12} aria-hidden="true" /> 선택 삭제
            </button>
          </>
        )}
      </BulkActionBar>

      {uploadNotice && (
        <Alert tone="info">
          <div className="documents-notice">
            <span>{uploadNotice}</span>
            <IconButton label="닫기" onClick={() => setUploadNotice(null)}>
              <X size={14} />
            </IconButton>
          </div>
        </Alert>
      )}

      {batchReprocess.isError && <ErrorAlert error={batchReprocess.error} message="선택한 문서를 재처리하지 못했습니다." />}
      {batchDelete.isError && <ErrorAlert error={batchDelete.error} message="선택한 문서를 삭제하지 못했습니다." />}
      {deleteDoc.isError && <ErrorAlert error={deleteDoc.error} message="문서를 삭제하지 못했습니다." />}

      {reprocessSummary && (
        <Alert tone="success">
          <div className="documents-notice">
            <span>{reprocessSummary}</span>
            <IconButton label="닫기" onClick={() => setReprocessSummary(null)}>
              <X size={14} />
            </IconButton>
          </div>
        </Alert>
      )}

      {isError && (
        <ErrorAlert error={error} message="문서 목록을 불러오지 못했습니다." onRetry={() => refetch()} />
      )}

      {isLoading ? (
        <div className="documents-center"><Spinner /></div>
      ) : isError ? null : !data?.items.length ? (
        hasActiveFilters ? (
          <EmptyState
            title="조건에 맞는 문서가 없습니다."
            description="필터를 바꾸거나 초기화해 보세요."
            action={<Button variant="secondary" size="sm" icon={<X size={14} />} onClick={clearFilters}>필터 초기화</Button>}
          />
        ) : (
          <EmptyState title="업로드된 문서가 없습니다." />
        )
      ) : (
        <Card isFlush>
          <DocumentsTable
            documents={data?.items}
            sortBy={sortBy}
            order={order}
            selectedIds={selectedIds}
            confirmDeleteId={confirmDeleteId}
            collectionsMap={Object.fromEntries(collectionsData?.items.map((c) => [c.id, c.name]) ?? [])}
            onToggleSort={toggleSort}
            onToggleSelect={toggleSelect}
            onToggleAll={toggleAll}
            onConfirmDelete={(id) => { deleteDoc.mutate(id); setConfirmDeleteId(null) }}
            onCancelDelete={() => setConfirmDeleteId(null)}
            onDeleteClick={setConfirmDeleteId}
            onDocumentClick={(id) => navigate(projectId ? `/projects/${projectId}/documents/${id}` : `/documents/${id}`)}
            isDeleting={deleteDoc.isPending}
          />
          <div className="documents-pager">
            <Button size="sm" variant="secondary" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page <= 1}>
              이전
            </Button>
            <span>{page} / {totalPages} 페이지 (총 {data.total}건)</span>
            <Button size="sm" variant="secondary" onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={page >= totalPages}>
              다음
            </Button>
          </div>
        </Card>
      )}

      {showUploadModal && (
        <UploadModal
          isOpen={showUploadModal}
          onClose={() => setShowUploadModal(false)}
          onUploaded={(message) => setUploadNotice(message)}
        />
      )}
    </Page>
  )
}
