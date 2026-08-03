import { useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { Upload, Trash2, Loader2, ArrowUp, ArrowDown, X } from 'lucide-react'
import { useDocuments, useUploadDocument, useUploadZip, useDeleteDocument, useBatchDeleteDocuments, type DocumentSortBy, type SortOrder, type BulkUploadResponse } from '../hooks/useDocuments'
import { useCollections } from '../hooks/useCollections'
import { useWorkflowVersions, useWorkflows } from '../hooks/useWorkflows'
import { STATUS_BADGE_CLASSES, STATUS_LABELS } from '../lib/documentStatus'

export default function DocumentsPage() {
  const fileRef = useRef<HTMLInputElement>(null)
  const navigate = useNavigate()
  const location = useLocation()
  const { projectId } = useParams<{ projectId?: string }>()
  const [searchParams] = useSearchParams()
  const [showUploadModal, setShowUploadModal] = useState(false)
  const [uploadCollectionId, setUploadCollectionId] = useState('')
  // '' = 컬렉션 기본 워크플로우 사용 — 업로드 다이얼로그의 워크플로우 오버라이드.
  const [uploadWorkflowId, setUploadWorkflowId] = useState('')
  const [skipReview, setSkipReview] = useState(false)
  const [selectedFiles, setSelectedFiles] = useState<File[]>([])
  const [uploadProgress, setUploadProgress] = useState<{ name: string; status: 'pending' | 'success' | 'error'; error?: string }[]>([])
  const [isBatchUploading, setIsBatchUploading] = useState(false)
  const [uploadMode, setUploadMode] = useState<'files' | 'zip'>('files')
  const zipFileRef = useRef<HTMLInputElement>(null)
  const [zipFile, setZipFile] = useState<File | null>(null)
  const [zipResult, setZipResult] = useState<BulkUploadResponse | null>(null)
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

  const { data, isLoading } = useDocuments({
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
  const upload = useUploadDocument()
  const uploadZip = useUploadZip()
  const deleteDoc = useDeleteDocument()
  const batchDelete = useBatchDeleteDocuments()
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null)
  const [confirmBulkDelete, setConfirmBulkDelete] = useState(false)
  const { data: collectionsData } = useCollections(projectId)
  const selectedUploadCollection = collectionsData?.items.find((c) => c.id === uploadCollectionId)
  const { data: uploadProjectWorkflows } = useWorkflows(selectedUploadCollection?.project_id ?? null, 'PREPROCESS')
  const { data: uploadWorkflowVersions } = useWorkflowVersions(uploadWorkflowId || null)
  // 업로드 API는 workflow_version_id(구체적 버전)를 받으므로, 선택된 워크플로우의
  // 최신 발행 버전으로 자동 해석한다 — 컬렉션 설정 화면과 달리 여기선 버전 고정
  // UI까지는 두지 않는다(업로드 시점의 빠른 오버라이드가 목적).
  const resolvedUploadWorkflowVersionId = uploadWorkflowId
    ? [...(uploadWorkflowVersions?.items ?? [])]
        .filter((v) => v.published_at)
        .sort((a, b) => b.version_number - a.version_number)[0]?.id
    : undefined

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

  const isMultiUpload = selectedFiles.length > 1
  const effectiveSkipReview = isMultiUpload ? true : skipReview

  const closeUploadModal = () => {
    setShowUploadModal(false)
    setUploadCollectionId('')
    setUploadWorkflowId('')
    setSkipReview(false)
    setSelectedFiles([])
    setUploadProgress([])
    setIsBatchUploading(false)
    setUploadMode('files')
    setZipFile(null)
    setZipResult(null)
    if (fileRef.current) fileRef.current.value = ''
    if (zipFileRef.current) zipFileRef.current.value = ''
  }

  const removeSelectedFile = (index: number) => {
    setSelectedFiles((prev) => prev.filter((_, i) => i !== index))
  }

  const handleZipUploadSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!zipFile || !uploadCollectionId) return
    setZipResult(null)
    try {
      const result = await uploadZip.mutateAsync({
        file: zipFile,
        collection_id: uploadCollectionId,
        skip_review: true,
        workflow_version_id: resolvedUploadWorkflowVersionId,
      })
      setZipResult(result)
    } catch (err) {
      setZipResult({
        total_entries: 0,
        queued: 0,
        results: [{
          filename: zipFile.name,
          status: 'failed',
          document_id: null,
          detail: err instanceof Error ? err.message : 'ZIP 업로드 실패',
        }],
      })
    }
  }

  const ZIP_STATUS_LABEL: Record<string, string> = {
    queued: '등록됨', duplicate: '중복', skipped: '건너뜀', failed: '실패',
  }
  const ZIP_STATUS_COLOR: Record<string, string> = {
    queued: '#16a34a', duplicate: '#d97706', skipped: 'var(--color-text-muted)', failed: '#dc2626',
  }

  const handleUploadSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!selectedFiles.length || !uploadCollectionId) return

    setIsBatchUploading(true)
    setUploadProgress(selectedFiles.map((f) => ({ name: f.name, status: 'pending' as const })))

    let successCount = 0
    for (let i = 0; i < selectedFiles.length; i++) {
      try {
        await upload.mutateAsync({
          file: selectedFiles[i],
          collection_id: uploadCollectionId,
          skip_review: effectiveSkipReview,
          workflow_version_id: resolvedUploadWorkflowVersionId,
        })
        successCount++
        setUploadProgress((prev) => prev.map((p, idx) => (idx === i ? { ...p, status: 'success' } : p)))
      } catch (err) {
        const message = err instanceof Error ? err.message : '업로드 실패'
        setUploadProgress((prev) => prev.map((p, idx) => (idx === i ? { ...p, status: 'error', error: message } : p)))
      }
    }
    setIsBatchUploading(false)

    if (successCount === selectedFiles.length) {
      closeUploadModal()
    }
  }

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

      <style>{`@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }`}</style>

      {isLoading ? (
        <p style={{ color: 'var(--color-text-muted)' }}>로딩 중...</p>
      ) : !data?.items.length ? (
        <p style={{ color: 'var(--color-text-muted)', textAlign: 'center', padding: 'var(--space-8)' }}>
          업로드된 문서가 없습니다.
        </p>
      ) : (
        <div className="krds-table-wrap">
          <table className="tbl col data" style={{ width: '100%' }}>
            <caption>문서 목록</caption>
            <thead>
              <tr>
                <th scope="col" style={{ width: '5%' }}>
                  <div className="krds-form-check">
                    <input
                      type="checkbox"
                      className="chk"
                      id="doc_chk_all"
                      checked={selectedIds.size > 0 && selectedIds.size === data?.items.length}
                      onChange={toggleAll}
                    />
                    <label htmlFor="doc_chk_all"></label>
                  </div>
                </th>
                {([
                  ['파일명', 'filename'],
                  ['컬렉션', null],
                  ['크기', 'file_size'],
                  ['상태', 'status'],
                  ['생성일', 'created_at'],
                  ['', null],
                ] as [string, DocumentSortBy | null][]).map(([label, column]) => (
                  <th
                    key={label}
                    scope="col"
                    onClick={column ? () => toggleSort(column) : undefined}
                    style={{ cursor: column ? 'pointer' : 'default', userSelect: 'none' }}
                  >
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                      {label}
                      {column && sortBy === column && (
                        order === 'asc' ? <ArrowUp size={12} /> : <ArrowDown size={12} />
                      )}
                    </span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.items.map((doc) => (
                <tr key={doc.id} style={{ background: selectedIds.has(doc.id) ? 'rgba(99,102,241,0.04)' : undefined }}>
                  <th scope="row">
                    <div className="krds-form-check">
                      <input
                        type="checkbox"
                        className="chk"
                        id={`doc_chk_${doc.id}`}
                        checked={selectedIds.has(doc.id)}
                        onChange={() => toggleSelect(doc.id)}
                      />
                      <label htmlFor={`doc_chk_${doc.id}`}></label>
                    </div>
                  </th>
                  <td style={{ cursor: 'pointer', color: 'var(--color-accent)' }} onClick={() => navigate(projectId ? `/projects/${projectId}/documents/${doc.id}` : `/documents/${doc.id}`)}>
                    {doc.original_filename}
                  </td>
                  <td style={{ color: 'var(--color-text-muted)' }}>
                    {doc.collection_id
                      ? (collectionsData?.items.find((c) => c.id === doc.collection_id)?.name ?? doc.collection_id.slice(0, 8))
                      : '-'}
                  </td>
                  <td style={{ color: 'var(--color-text-muted)' }}>
                    {(doc.file_size / 1024).toFixed(1)} KB
                  </td>
                  <td>
                    <span className={`krds-badge ${STATUS_BADGE_CLASSES[doc.status] ?? 'bg-gray'}`}>
                      {STATUS_LABELS[doc.status] ?? doc.status}
                    </span>
                    {doc.ocr_used && (
                      <span
                        className="krds-badge xsmall bg-information"
                        style={{ marginLeft: 'var(--space-2)' }}
                        title="스캔 이미지 페이지를 OCR로 인식한 문서입니다."
                      >
                        OCR
                      </span>
                    )}
                    {doc.status === 'FAILED' && doc.error_message && (
                      <span style={{ marginLeft: 'var(--space-2)', fontSize: 11, color: 'var(--color-danger)' }} title={doc.error_message}>⚠</span>
                    )}
                  </td>
                  <td style={{ color: 'var(--color-text-muted)' }}>
                    {new Date(doc.created_at).toLocaleDateString('ko-KR')}
                  </td>
                  <td>
                    {confirmDeleteId === doc.id ? (
                      <div style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'center' }}>
                        <span style={{ fontSize: 12, color: '#dc2626' }}>삭제하시겠습니까?</span>
                        <button
                          onClick={() => { deleteDoc.mutate(doc.id); setConfirmDeleteId(null) }}
                          disabled={deleteDoc.isPending}
                          className="krds-btn xsmall primary"
                        >
                          확인
                        </button>
                        <button onClick={() => setConfirmDeleteId(null)} className="krds-btn xsmall secondary">
                          취소
                        </button>
                      </div>
                    ) : (
                      <button
                        onClick={() => setConfirmDeleteId(doc.id)}
                        className="krds-btn text xsmall icon-btn danger"
                      >
                        <Trash2 size={14} />
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
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

      {showUploadModal && (
        <div style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 50,
        }}>
        <section className="krds-modal fade shown in" role="dialog">
          <div className="modal-dialog modal-sm">
            <div className="modal-content">
              <div className="modal-header">
                <h2 className="modal-title">문서 업로드</h2>
              </div>
              <div className="modal-conts">
                <div className="conts-area">
                  <div style={{ display: 'flex', gap: 'var(--space-2)', marginBottom: 'var(--space-4)' }}>
                    <button
                      type="button"
                      onClick={() => setUploadMode('files')}
                      className={`krds-btn small ${uploadMode === 'files' ? 'primary' : 'secondary'}`}
                      style={{ flex: 1 }}
                    >
                      개별 파일
                    </button>
                    <button
                      type="button"
                      onClick={() => setUploadMode('zip')}
                      className={`krds-btn small ${uploadMode === 'zip' ? 'primary' : 'secondary'}`}
                      style={{ flex: 1 }}
                    >
                      ZIP 일괄 업로드
                    </button>
                  </div>

                  {uploadMode === 'files' && (
                  <form onSubmit={handleUploadSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
                    <div className="form-group">
                      <div className="form-tit">
                        <label htmlFor="upload_collection">
                          컬렉션 <span style={{ color: 'var(--color-danger)' }}>*</span>
                        </label>
                      </div>
                      <div className="form-conts">
                        <select
                          id="upload_collection"
                          value={uploadCollectionId}
                          onChange={(e) => { setUploadCollectionId(e.target.value); setUploadWorkflowId('') }}
                          className="krds-form-select"
                          style={{ width: '100%' }}
                          required
                        >
                          <option value="">컬렉션을 선택하세요</option>
                          {collectionsData?.items.map((c) => (
                            <option key={c.id} value={c.id}>{c.name}</option>
                          ))}
                        </select>
                        {!collectionsData?.items.length && (
                          <p className="form-hint-invalid">
                            컬렉션이 없습니다. 먼저 컬렉션을 생성하세요.
                          </p>
                        )}
                      </div>
                    </div>

                    {uploadCollectionId && (
                      <div className="form-group">
                        <div className="form-tit">
                          <label htmlFor="upload_workflow">전처리 워크플로우</label>
                        </div>
                        <div className="form-conts">
                          <select
                            id="upload_workflow"
                            value={uploadWorkflowId}
                            onChange={(e) => setUploadWorkflowId(e.target.value)}
                            className="krds-form-select"
                            style={{ width: '100%' }}
                          >
                            <option value="">컬렉션 기본값 사용</option>
                            {(uploadProjectWorkflows?.items ?? []).filter((wf) => !wf.is_system_default).map((wf) => (
                              <option key={wf.id} value={wf.id}>{wf.name}</option>
                            ))}
                          </select>
                        </div>
                      </div>
                    )}

                    <div className="form-group">
                      <div className="form-tit">
                        <label htmlFor="upload_file">
                          파일 <span style={{ color: 'var(--color-danger)' }}>*</span>
                        </label>
                      </div>
                      <div className="form-conts">
                        <button
                          type="button"
                          onClick={() => fileRef.current?.click()}
                          className="krds-btn medium"
                          style={{
                            width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center',
                            gap: 'var(--space-2)', border: '1px dashed var(--color-border)',
                          }}
                        >
                          <Upload size={16} />
                          {selectedFiles.length > 0 ? `${selectedFiles.length}개 파일 선택됨 (추가 선택)` : '파일 선택 (.pdf, .hwp, .hwpx, .docx)'}
                        </button>
                        <input
                          ref={fileRef} type="file" hidden id="upload_file" multiple
                          accept=".pdf,.hwp,.hwpx,.docx"
                          onChange={(e) => {
                            const newFiles = Array.from(e.target.files ?? [])
                            setSelectedFiles((prev) => [...prev, ...newFiles])
                            if (fileRef.current) fileRef.current.value = ''
                          }}
                        />
                        {selectedFiles.length > 0 && (
                          <div style={{
                            display: 'flex', flexDirection: 'column', gap: 'var(--space-1)',
                            maxHeight: 160, overflowY: 'auto', width: '100%',
                          }}>
                            {selectedFiles.map((f, i) => {
                              const progress = uploadProgress[i]
                              return (
                                <div
                                  key={`${f.name}-${i}`}
                                  style={{
                                    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                                    fontSize: 13, padding: 'var(--space-1) var(--space-2)',
                                    background: '#f8fafc', borderRadius: 'var(--radius-sm)', gap: 'var(--space-2)',
                                  }}
                                >
                                  <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={progress?.error}>
                                    {f.name}
                                  </span>
                                  {progress?.status === 'success' && <span style={{ color: '#16a34a', flexShrink: 0 }}>✓</span>}
                                  {progress?.status === 'error' && <span style={{ color: 'var(--color-danger)', flexShrink: 0 }} title={progress.error}>✕</span>}
                                  {progress?.status === 'pending' && isBatchUploading && (
                                    <Loader2 size={12} style={{ animation: 'spin 1s linear infinite', flexShrink: 0 }} />
                                  )}
                                  {!progress && (
                                    <button
                                      type="button"
                                      onClick={() => removeSelectedFile(i)}
                                      className="krds-btn text xsmall icon-btn"
                                      style={{ flexShrink: 0 }}
                                    >
                                      <X size={12} />
                                    </button>
                                  )}
                                </div>
                              )
                            })}
                          </div>
                        )}
                      </div>
                    </div>

                    <div className="krds-form-check">
                      <input
                        id="skip_review_chk"
                        type="checkbox" checked={effectiveSkipReview}
                        disabled={isMultiUpload}
                        onChange={(e) => setSkipReview(e.target.checked)}
                      />
                      <label htmlFor="skip_review_chk">
                        검토 없이 자동 진행 (파싱 후 바로 청킹·임베딩까지 처리)
                        {isMultiUpload && (
                          <span style={{ color: 'var(--color-text-muted)' }}> — 파일이 2개 이상이면 자동 적용됩니다</span>
                        )}
                      </label>
                    </div>

                    {uploadProgress.length > 0 && !isBatchUploading && uploadProgress.some((p) => p.status === 'error') && (
                      <div style={{
                        background: '#fef2f2', border: '1px solid #fecaca',
                        borderRadius: 'var(--radius-md)', padding: 'var(--space-3)',
                        color: '#dc2626', fontSize: 13,
                      }}>
                        {uploadProgress.filter((p) => p.status === 'success').length}/{uploadProgress.length}개 성공,
                        {' '}{uploadProgress.filter((p) => p.status === 'error').length}개 실패했습니다. 실패한 파일을 확인하세요.
                      </div>
                    )}

                    <div className="modal-btn btn-wrap">
                      <button type="button" onClick={closeUploadModal} className="krds-btn medium secondary">
                        취소
                      </button>
                      <button
                        type="submit"
                        disabled={isBatchUploading || !selectedFiles.length || !uploadCollectionId}
                        className="krds-btn medium primary"
                        style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', justifyContent: 'center', opacity: (isBatchUploading || !selectedFiles.length || !uploadCollectionId) ? 0.7 : 1 }}
                      >
                        {isBatchUploading && <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} />}
                        {selectedFiles.length > 1 ? `${selectedFiles.length}개 업로드` : '업로드'}
                      </button>
                    </div>
                  </form>
                  )}

                  {uploadMode === 'zip' && (
                  <form onSubmit={handleZipUploadSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
                    <div className="form-group">
                      <div className="form-tit">
                        <label htmlFor="upload_zip_collection">
                          컬렉션 <span style={{ color: 'var(--color-danger)' }}>*</span>
                        </label>
                      </div>
                      <div className="form-conts">
                        <select
                          id="upload_zip_collection"
                          value={uploadCollectionId}
                          onChange={(e) => { setUploadCollectionId(e.target.value); setUploadWorkflowId('') }}
                          className="krds-form-select"
                          style={{ width: '100%' }}
                          required
                        >
                          <option value="">컬렉션을 선택하세요</option>
                          {collectionsData?.items.map((c) => (
                            <option key={c.id} value={c.id}>{c.name}</option>
                          ))}
                        </select>
                      </div>
                    </div>

                    {uploadCollectionId && (
                      <div className="form-group">
                        <div className="form-tit">
                          <label htmlFor="upload_zip_workflow">전처리 워크플로우</label>
                        </div>
                        <div className="form-conts">
                          <select
                            id="upload_zip_workflow"
                            value={uploadWorkflowId}
                            onChange={(e) => setUploadWorkflowId(e.target.value)}
                            className="krds-form-select"
                            style={{ width: '100%' }}
                          >
                            <option value="">컬렉션 기본값 사용</option>
                            {(uploadProjectWorkflows?.items ?? []).filter((wf) => !wf.is_system_default).map((wf) => (
                              <option key={wf.id} value={wf.id}>{wf.name}</option>
                            ))}
                          </select>
                        </div>
                      </div>
                    )}

                    <div className="form-group">
                      <div className="form-tit">
                        <label htmlFor="upload_zip_file">
                          ZIP 파일 <span style={{ color: 'var(--color-danger)' }}>*</span>
                        </label>
                      </div>
                      <div className="form-conts">
                        <button
                          type="button"
                          onClick={() => zipFileRef.current?.click()}
                          className="krds-btn medium"
                          style={{
                            width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center',
                            gap: 'var(--space-2)', border: '1px dashed var(--color-border)',
                          }}
                        >
                          <Upload size={16} />
                          {zipFile ? zipFile.name : 'ZIP 파일 선택 (.zip)'}
                        </button>
                        <input
                          ref={zipFileRef} type="file" hidden id="upload_zip_file"
                          accept=".zip"
                          onChange={(e) => {
                            setZipFile(e.target.files?.[0] ?? null)
                            setZipResult(null)
                          }}
                        />
                        <p className="form-hint" style={{ marginTop: 'var(--space-2)' }}>
                          ZIP 안의 PDF/HWP/HWPX/DOCX 파일을 자동으로 추출해 개별 문서로 등록합니다.
                          지원하지 않는 형식이나 중복 파일은 건너뜁니다.
                        </p>
                      </div>
                    </div>

                    {zipResult && (
                      <div style={{
                        border: '1px solid var(--color-border)', borderRadius: 'var(--radius-md)',
                        padding: 'var(--space-3)', fontSize: 13, display: 'flex', flexDirection: 'column', gap: 'var(--space-2)',
                      }}>
                        <strong>
                          총 {zipResult.total_entries}개 중 {zipResult.queued}개 등록됨
                        </strong>
                        <div style={{ maxHeight: 180, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 'var(--space-1)' }}>
                          {zipResult.results.map((r, i) => (
                            <div
                              key={`${r.filename}-${i}`}
                              style={{
                                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                                gap: 'var(--space-2)', padding: 'var(--space-1) var(--space-2)',
                                background: '#f8fafc', borderRadius: 'var(--radius-sm)',
                              }}
                              title={r.detail ?? undefined}
                            >
                              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                {r.filename}
                              </span>
                              <span style={{ color: ZIP_STATUS_COLOR[r.status], flexShrink: 0, fontWeight: 600 }}>
                                {ZIP_STATUS_LABEL[r.status]}
                              </span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    <div className="modal-btn btn-wrap">
                      <button type="button" onClick={closeUploadModal} className="krds-btn medium secondary">
                        닫기
                      </button>
                      <button
                        type="submit"
                        disabled={uploadZip.isPending || !zipFile || !uploadCollectionId}
                        className="krds-btn medium primary"
                        style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', justifyContent: 'center', opacity: (uploadZip.isPending || !zipFile || !uploadCollectionId) ? 0.7 : 1 }}
                      >
                        {uploadZip.isPending && <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} />}
                        ZIP 업로드
                      </button>
                    </div>
                  </form>
                  )}
                </div>
              </div>
              <button type="button" onClick={closeUploadModal} className="krds-btn medium icon btn-close">
                <span className="sr-only">닫기</span>
                <X size={20} />
              </button>
            </div>
          </div>
          <div className="modal-back"></div>
        </section>
        </div>
      )}
    </div>
  )
}
