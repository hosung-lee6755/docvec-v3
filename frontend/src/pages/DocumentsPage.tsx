import { useEffect, useState } from 'react'
import { useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { Upload, Trash2, X, RefreshCw } from 'lucide-react'
import { useDocuments, useDeleteDocument, useBatchDeleteDocuments, useBatchReprocessDocuments, type DocumentSortBy, type SortOrder } from '../hooks/useDocuments'
import { useCollections } from '../hooks/useCollections'
import { STATUS_LABELS } from '../lib/documentStatus'
import { DocumentsTable } from '../components/documents/DocumentsTable'
import { UploadModal } from '../components/documents/UploadModal'

export default function DocumentsPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const { projectId } = useParams<{ projectId?: string }>()
  const [searchParams] = useSearchParams()
  const [showUploadModal, setShowUploadModal] = useState(false)
  const [filterCollectionId, setFilterCollectionId] = useState(() => searchParams.get('collection') ?? '')
  const [filterStatus, setFilterStatus] = useState('')
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
    setFilterStatus(searchParams.get('status') ?? '')
  }, [searchParams])

  useEffect(() => {
    if ((location.state as { openUpload?: boolean } | null)?.openUpload) {
      setShowUploadModal(true)
      navigate(location.pathname, { replace: true, state: null })
    }
  }, [location, navigate])

  const { data, isLoading, isError, refetch } = useDocuments({
    page,
    limit,
    collectionId: filterCollectionId,
    projectId,
    status: filterStatus,
    filename: filenameFilter,
    sortBy,
    order,
  })
  const totalPages = Math.max(1, Math.ceil((data?.total ?? 0) / limit))

  // 필터/정렬/표시건수가 바뀌면 이전 페이지 번호가 새 결과 범위를 벗어날 수
  // 있어(예: 3페이지 보다가 필터링하면 결과가 1페이지뿐) 1페이지로 되돌린다.
  useEffect(() => {
    setPage(1)
  }, [filterCollectionId, filterStatus, filenameFilter, sortBy, order, limit])
  const deleteDoc = useDeleteDocument()
  const batchDelete = useBatchDeleteDocuments()
  const batchReprocess = useBatchReprocessDocuments()
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null)
  const [confirmBulkDelete, setConfirmBulkDelete] = useState(false)
  const [reprocessSummary, setReprocessSummary] = useState<string | null>(null)
  const { data: collectionsData } = useCollections(projectId)

  const toggleSort = (column: DocumentSortBy) => {
    if (sortBy === column) {
      setOrder((o) => (o === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortBy(column)
      setOrder('asc')
    }
  }

  const hasActiveFilters = !!(filterCollectionId || filterStatus || filenameFilter)
  const clearFilters = () => {
    setFilterCollectionId('')
    setFilterStatus('')
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

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 'var(--space-4)' }}>
        <h1 style={{ fontSize: 24, fontWeight: 700 }}>문서</h1>
        <button
          type="button"
          onClick={() => setShowUploadModal(true)}
          className="krds-btn small primary"
          style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-1)' }}
        >
          <Upload size={14} /> 문서 업로드
        </button>
      </div>

      <div style={{
        display: 'flex', alignItems: 'center', gap: 'var(--space-3)',
        marginBottom: 'var(--space-4)', flexWrap: 'wrap',
      }}>
        <select
          value={filterCollectionId}
          onChange={(e) => setFilterCollectionId(e.target.value)}
          className="krds-form-select small"
          style={{ flex: '0 0 180px', width: 180 }}
        >
          <option value="">전체 컬렉션</option>
          {collectionsData?.items.map((c) => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>

        <select
          value={filterStatus}
          onChange={(e) => setFilterStatus(e.target.value)}
          className="krds-form-select small"
          style={{ flex: '0 0 140px', width: 140 }}
        >
          <option value="">전체 상태</option>
          {Object.entries(STATUS_LABELS).map(([value, label]) => (
            <option key={value} value={value}>{label}</option>
          ))}
        </select>

        <input
          value={filenameInput}
          onChange={(e) => setFilenameInput(e.target.value)}
          placeholder="파일명 검색..."
          className="krds-input small"
          style={{ flex: 1, minWidth: 160 }}
        />

        {hasActiveFilters && (
          <button
            onClick={clearFilters}
            className="krds-btn small text"
            style={{ display: 'flex', alignItems: 'center', gap: 4 }}
          >
            <X size={14} /> 필터 초기화
          </button>
        )}

        <select
          value={limit}
          onChange={(e) => setLimit(Number(e.target.value))}
          className="krds-form-select small"
          style={{ flex: '0 0 110px', width: 110 }}
        >
          {[10, 20, 50, 100, 200].map((n) => (
            <option key={n} value={n}>{n}건씩 보기</option>
          ))}
        </select>
      </div>

      {selectedIds.size > 0 && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 'var(--space-3)',
          marginBottom: 'var(--space-3)', padding: 'var(--space-2) var(--space-4)',
          background: '#eff6ff', border: '1px solid #bfdbfe',
          borderRadius: 'var(--radius-md)',
        }}>
          <span style={{ fontSize: 14, fontWeight: 500 }}>
            {selectedIds.size}개 선택됨
          </span>
          {confirmBulkDelete ? (
            <>
              <span style={{ fontSize: 12, color: '#dc2626' }}>정말 삭제하시겠습니까?</span>
              <button
                disabled={batchDelete.isPending}
                onClick={() => batchDelete.mutate([...selectedIds], {
                  onSuccess: () => { setSelectedIds(new Set()); setConfirmBulkDelete(false) },
                })}
                className="krds-btn xsmall primary"
              >
                확인
              </button>
              <button onClick={() => setConfirmBulkDelete(false)} className="krds-btn xsmall secondary">
                취소
              </button>
            </>
          ) : (
            <>
              <button
                disabled={batchReprocess.isPending}
                onClick={() => {
                  const ids = [...selectedIds]
                  batchReprocess.mutate(ids, {
                    onSuccess: (data) => {
                      const queued = data.results.filter((r) => r.status === 'queued').length
                      const skipped = data.results.filter((r) => r.status === 'skipped').length
                      const failed = data.results.filter((r) => r.status === 'failed').length
                      setReprocessSummary(
                        `재처리 시작 ${queued}건` +
                        (skipped ? `, 건너뜀 ${skipped}건(실패 상태 아님)` : '') +
                        (failed ? `, 실패 ${failed}건` : ''),
                      )
                      setSelectedIds(new Set())
                    },
                  })
                }}
                className="krds-btn small tertiary"
                style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-1)' }}
              >
                <RefreshCw size={14} /> {batchReprocess.isPending ? '재처리 요청 중...' : '선택 재처리'}
              </button>
              <button
                onClick={() => setConfirmBulkDelete(true)}
                className="krds-btn small tertiary"
                style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-1)', color: '#dc2626' }}
              >
                <Trash2 size={14} /> 선택 삭제
              </button>
              <button
                onClick={() => { setSelectedIds(new Set()); setConfirmBulkDelete(false) }}
                className="krds-btn small tertiary"
              >
                선택 해제
              </button>
            </>
          )}
        </div>
      )}

      {reprocessSummary && (
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          marginBottom: 'var(--space-3)', padding: 'var(--space-2) var(--space-4)',
          background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: 'var(--radius-md)',
          fontSize: 14,
        }}>
          <span>{reprocessSummary}</span>
          <button
            onClick={() => setReprocessSummary(null)}
            className="krds-btn xsmall tertiary"
            style={{ display: 'flex', alignItems: 'center' }}
            aria-label="닫기"
          >
            <X size={14} />
          </button>
        </div>
      )}

      <style>{`@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }`}</style>

      {isError && (
        <div style={{
          background: '#fef2f2', border: '1px solid #fecaca',
          borderRadius: 'var(--radius-md)', padding: 'var(--space-4)',
          color: '#dc2626', marginBottom: 'var(--space-4)',
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        }}>
          <span>문서 목록을 불러올 수 없습니다.</span>
          <button
            onClick={() => refetch()}
            className="krds-btn small secondary"
            style={{ marginLeft: 'var(--space-4)' }}
          >
            <RefreshCw size={14} style={{ marginRight: 4 }} />
            다시 시도
          </button>
        </div>
      )}

      {isLoading ? (
        <p style={{ color: 'var(--color-text-muted)' }}>로딩 중...</p>
      ) : isError ? null : !data?.items.length ? (
        <p style={{ color: 'var(--color-text-muted)', textAlign: 'center', padding: 'var(--space-8)' }}>
          업로드된 문서가 없습니다.
        </p>
      ) : (
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
      )}

      {!!data?.items.length && (
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 'var(--space-3)',
          marginTop: 'var(--space-4)',
        }}>
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
            className="krds-btn small secondary"
          >
            이전
          </button>
          <span style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>
            {page} / {totalPages} 페이지 (총 {data.total}건)
          </span>
          <button
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages}
            className="krds-btn small secondary"
          >
            다음
          </button>
        </div>
      )}

      {showUploadModal && <UploadModal isOpen={showUploadModal} onClose={() => setShowUploadModal(false)} />}
    </div>
  )
}
