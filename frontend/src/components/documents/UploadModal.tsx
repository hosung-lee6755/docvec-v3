import { useRef, useState } from 'react'
import { Loader2, Upload, X } from 'lucide-react'
import { useUploadDocument, useUploadZip, type BulkUploadResponse } from '../../hooks/useDocuments'
import { useCollections } from '../../hooks/useCollections'
import { useWorkflows, useWorkflowVersions } from '../../hooks/useWorkflows'

interface UploadModalProps {
  isOpen: boolean
  onClose: () => void
  // 여러 파일을 올리고 모달이 닫힐 때, 새 버전으로 묶인 파일이 있으면 그 안내를 부모가 보여준다.
  onUploaded?: (message: string) => void
}

const versionNoticeFor = (version: number | null | undefined) =>
  version && version > 1 ? `기존 문서의 ${version}번째 버전으로 올렸습니다.` : null

export function UploadModal({
  isOpen,
  onClose,
  onUploaded,
}: UploadModalProps) {
  const fileRef = useRef<HTMLInputElement>(null)
  const zipFileRef = useRef<HTMLInputElement>(null)

  const [uploadCollectionId, setUploadCollectionId] = useState('')
  const [uploadWorkflowId, setUploadWorkflowId] = useState('')
  const [skipReview, setSkipReview] = useState(false)
  const [selectedFiles, setSelectedFiles] = useState<File[]>([])
  const [uploadProgress, setUploadProgress] = useState<{ name: string; status: 'pending' | 'success' | 'error'; error?: string }[]>([])
  const [isBatchUploading, setIsBatchUploading] = useState(false)
  const [uploadMode, setUploadMode] = useState<'files' | 'zip'>('files')
  const [zipFile, setZipFile] = useState<File | null>(null)
  const [zipResult, setZipResult] = useState<BulkUploadResponse | null>(null)
  const [newDocument, setNewDocument] = useState(false)

  const upload = useUploadDocument()
  const uploadZip = useUploadZip()
  const { data: collectionsDataFull } = useCollections()
  const collectionsData = collectionsDataFull?.items
  const selectedUploadCollection = collectionsData?.find((c) => c.id === uploadCollectionId)
  const { data: uploadProjectWorkflowsData } = useWorkflows(selectedUploadCollection?.project_id ?? null, 'PREPROCESS')
  const uploadProjectWorkflows = uploadProjectWorkflowsData?.items
  const { data: uploadWorkflowVersionsData } = useWorkflowVersions(uploadWorkflowId || null)
  const uploadWorkflowVersions = uploadWorkflowVersionsData?.items

  const resolvedUploadWorkflowVersionId = uploadWorkflowId
    ? [...(uploadWorkflowVersions ?? [])]
        .filter((v) => v.published_at)
        .sort((a, b) => b.version_number - a.version_number)[0]?.id
    : undefined

  const isMultiUpload = selectedFiles.length > 1
  const effectiveSkipReview = isMultiUpload ? true : skipReview

  const closeUploadModal = () => {
    onClose()
    setUploadCollectionId('')
    setUploadWorkflowId('')
    setSkipReview(false)
    setSelectedFiles([])
    setUploadProgress([])
    setIsBatchUploading(false)
    setUploadMode('files')
    setZipFile(null)
    setZipResult(null)
    setNewDocument(false)
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
        new_document: newDocument,
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

  const handleUploadSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!selectedFiles.length || !uploadCollectionId) return

    setIsBatchUploading(true)
    setUploadProgress(selectedFiles.map((f) => ({ name: f.name, status: 'pending' as const })))

    let successCount = 0
    const versionNotices: string[] = []
    for (let i = 0; i < selectedFiles.length; i++) {
      try {
        const result = await upload.mutateAsync({
          file: selectedFiles[i],
          collection_id: uploadCollectionId,
          skip_review: effectiveSkipReview,
          workflow_version_id: resolvedUploadWorkflowVersionId,
          new_document: newDocument,
        })
        const notice = versionNoticeFor(result.version_number)
        if (notice) versionNotices.push(`${selectedFiles[i].name}: ${notice}`)
        successCount++
        setUploadProgress((prev) => prev.map((p, idx) => (idx === i ? { ...p, status: 'success' } : p)))
      } catch (err) {
        const message = err instanceof Error ? err.message : '업로드 실패'
        setUploadProgress((prev) => prev.map((p, idx) => (idx === i ? { ...p, status: 'error', error: message } : p)))
      }
    }
    setIsBatchUploading(false)

    if (successCount === selectedFiles.length) {
      if (versionNotices.length) onUploaded?.(versionNotices.join(' '))
      closeUploadModal()
    }
  }

  const ZIP_STATUS_LABEL: Record<string, string> = {
    queued: '등록됨', duplicate: '중복', skipped: '건너뜀', failed: '실패',
  }
  const ZIP_STATUS_COLOR: Record<string, string> = {
    queued: '#16a34a', duplicate: '#d97706', skipped: 'var(--color-text-muted)', failed: '#dc2626',
  }

  if (!isOpen) return null

  return (
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
                          {collectionsData?.map((c) => (
                            <option key={c.id} value={c.id}>{c.name}</option>
                          ))}
                        </select>
                        {!collectionsData?.length && (
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
                            {(uploadProjectWorkflows ?? []).filter((wf) => !wf.is_system_default).map((wf) => (
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
                        id="new_document_chk"
                        type="checkbox" checked={newDocument}
                        onChange={(e) => setNewDocument(e.target.checked)}
                      />
                      <label htmlFor="new_document_chk">
                        이름이 같아도 새 문서로 올리기
                        <span style={{ color: 'var(--color-text-muted)' }}> — 끄면 같은 이름의 문서는 새 버전으로 잇습니다</span>
                      </label>
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
                          {collectionsData?.map((c) => (
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
                            {(uploadProjectWorkflows ?? []).filter((wf) => !wf.is_system_default).map((wf) => (
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
                        <div className="krds-form-check" style={{ marginTop: 'var(--space-2)' }}>
                          <input
                            id="zip_new_document_chk"
                            type="checkbox" checked={newDocument}
                            onChange={(e) => setNewDocument(e.target.checked)}
                          />
                          <label htmlFor="zip_new_document_chk">이름이 같아도 새 문서로 올리기</label>
                        </div>
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
                        {zipResult.results
                          .filter((r) => versionNoticeFor(r.version_number))
                          .map((r, i) => (
                            <p key={`version-${r.filename}-${i}`} style={{ margin: 0, color: 'var(--color-accent)' }}>
                              {r.filename}: {versionNoticeFor(r.version_number)}
                            </p>
                          ))}
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
  )
}
