import { useRef, useState } from 'react'
import { Upload, X } from 'lucide-react'
import { useUploadDocument, useUploadZip, type BulkUploadResponse } from '../../hooks/useDocuments'
import { useCollections } from '../../hooks/useCollections'
import { useWorkflows, useWorkflowVersions } from '../../hooks/useWorkflows'
import { Alert, Badge, Button, Field, IconButton, Modal, Select, Spinner, Tabs } from '../ui'
import type { BadgeTone } from '../ui'
import '../../styles/screens/documents.css'

interface UploadModalProps {
  isOpen: boolean
  onClose: () => void
  // 여러 파일을 올리고 모달이 닫힐 때, 새 버전으로 묶인 파일이 있으면 그 안내를 부모가 보여준다.
  onUploaded?: (message: string) => void
}

type UploadMode = 'files' | 'zip'
type UploadRowStatus = 'pending' | 'success' | 'error'

const UPLOAD_MODE_ITEMS: { value: UploadMode; label: string }[] = [
  { value: 'files', label: '개별 파일' },
  { value: 'zip', label: 'ZIP 일괄 업로드' },
]

const ZIP_STATUS_LABEL: Record<string, string> = {
  queued: '등록됨', duplicate: '중복', skipped: '건너뜀', failed: '실패',
}
const ZIP_STATUS_TONE: Record<string, BadgeTone> = {
  queued: 'success', duplicate: 'warning', skipped: 'neutral', failed: 'danger',
}

const versionNoticeFor = (version: number | null | undefined) =>
  version && version > 1 ? `기존 문서의 ${version}번째 버전으로 올렸습니다.` : null

const FILES_FORM_ID = 'upload-files-form'
const ZIP_FORM_ID = 'upload-zip-form'

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
  const [uploadProgress, setUploadProgress] = useState<{ name: string; status: UploadRowStatus; error?: string }[]>([])
  const [isBatchUploading, setIsBatchUploading] = useState(false)
  const [uploadMode, setUploadMode] = useState<UploadMode>('files')
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

  const filesSubmitDisabled = isBatchUploading || !selectedFiles.length || !uploadCollectionId
  const zipSubmitDisabled = uploadZip.isPending || !zipFile || !uploadCollectionId
  const workflowOptions = (uploadProjectWorkflows ?? []).filter((wf) => !wf.is_system_default)
  const collectionMissingHint = !collectionsData?.length ? '컬렉션이 없습니다. 먼저 컬렉션을 생성하세요.' : undefined

  const footer = uploadMode === 'files' ? (
    <>
      <Button variant="secondary" onClick={closeUploadModal}>취소</Button>
      <Button
        type="submit"
        form={FILES_FORM_ID}
        variant="primary"
        disabled={filesSubmitDisabled}
        icon={isBatchUploading ? <Spinner size={14} /> : undefined}
      >
        {selectedFiles.length > 1 ? `${selectedFiles.length}개 업로드` : '업로드'}
      </Button>
    </>
  ) : (
    <>
      <Button variant="secondary" onClick={closeUploadModal}>닫기</Button>
      <Button
        type="submit"
        form={ZIP_FORM_ID}
        variant="primary"
        disabled={zipSubmitDisabled}
        icon={uploadZip.isPending ? <Spinner size={14} /> : undefined}
      >
        ZIP 업로드
      </Button>
    </>
  )

  return (
    <Modal isOpen={isOpen} title="문서 업로드" onClose={closeUploadModal} footer={footer}>
      <Tabs
        items={UPLOAD_MODE_ITEMS}
        value={uploadMode}
        onChange={setUploadMode}
        label="업로드 방식"
        idPrefix="upload"
      />

      <div role="tabpanel" id={`upload-panel-${uploadMode}`} aria-labelledby={`upload-tab-${uploadMode}`} className="documents-stack">
        {uploadMode === 'files' && (
          <form id={FILES_FORM_ID} className="documents-stack" onSubmit={handleUploadSubmit}>
            <Field
              label={<>컬렉션 <span className="documents-text-danger">*</span></>}
              error={collectionMissingHint}
            >
              {(id) => (
                <Select
                  id={id}
                  value={uploadCollectionId}
                  onChange={(e) => { setUploadCollectionId(e.target.value); setUploadWorkflowId('') }}
                  required
                >
                  <option value="">컬렉션을 선택하세요</option>
                  {collectionsData?.map((c) => (
                    <option key={c.id} value={c.id}>{c.name}</option>
                  ))}
                </Select>
              )}
            </Field>

            {uploadCollectionId && (
              <Field label="전처리 워크플로우">
                {(id) => (
                  <Select id={id} value={uploadWorkflowId} onChange={(e) => setUploadWorkflowId(e.target.value)}>
                    <option value="">컬렉션 기본값 사용</option>
                    {workflowOptions.map((wf) => (
                      <option key={wf.id} value={wf.id}>{wf.name}</option>
                    ))}
                  </Select>
                )}
              </Field>
            )}

            <div className="ds-field">
              <span className="ds-field__label">파일 <span className="documents-text-danger">*</span></span>
              <Button
                    variant="secondary"
                    className="documents-dropzone"
                    icon={<Upload size={16} />}
                    onClick={() => fileRef.current?.click()}
                  >
                    {selectedFiles.length > 0 ? `${selectedFiles.length}개 파일 선택됨 (추가 선택)` : '파일 선택 (.pdf, .hwp, .hwpx, .docx)'}
                  </Button>
                  <input
                    ref={fileRef}
                    type="file"
                    hidden
                    multiple
                    accept=".pdf,.hwp,.hwpx,.docx"
                    aria-label="업로드할 파일"
                    onChange={(e) => {
                      const newFiles = Array.from(e.target.files ?? [])
                      setSelectedFiles((prev) => [...prev, ...newFiles])
                      if (fileRef.current) fileRef.current.value = ''
                    }}
                  />
                  {selectedFiles.length > 0 && (
                    <div className="documents-file-list">
                      {selectedFiles.map((f, i) => {
                        const progress = uploadProgress[i]
                        return (
                          <div key={`${f.name}-${i}`} className="documents-file-row">
                            <span className="documents-ellipsis" title={progress?.error}>{f.name}</span>
                            {progress?.status === 'success' && <span className="documents-text-success" aria-label="성공">✓</span>}
                            {progress?.status === 'error' && <span className="documents-text-danger" title={progress.error} aria-label="실패">✕</span>}
                            {progress?.status === 'pending' && isBatchUploading && <Spinner size={12} />}
                            {!progress && (
                              <IconButton label={`${f.name} 목록에서 빼기`} onClick={() => removeSelectedFile(i)}>
                                <X size={12} />
                              </IconButton>
                            )}
                          </div>
                        )
                      })}
                    </div>
                  )}
            </div>

            <label className="documents-check">
              <input type="checkbox" checked={newDocument} onChange={(e) => setNewDocument(e.target.checked)} />
              <span>
                이름이 같아도 새 문서로 올리기
                <span className="documents-check-desc"> — 끄면 같은 이름의 문서는 새 버전으로 잇습니다</span>
              </span>
            </label>

            <label className="documents-check">
              <input
                type="checkbox"
                checked={effectiveSkipReview}
                disabled={isMultiUpload}
                onChange={(e) => setSkipReview(e.target.checked)}
              />
              <span>
                검토 없이 자동 진행 (파싱 후 바로 청킹·임베딩까지 처리)
                {isMultiUpload && (
                  <span className="documents-check-desc"> — 파일이 2개 이상이면 자동 적용됩니다</span>
                )}
              </span>
            </label>

            {uploadProgress.length > 0 && !isBatchUploading && uploadProgress.some((p) => p.status === 'error') && (
              <Alert tone="danger">
                {uploadProgress.filter((p) => p.status === 'success').length}/{uploadProgress.length}개 성공,
                {' '}{uploadProgress.filter((p) => p.status === 'error').length}개 실패했습니다. 실패한 파일을 확인하세요.
              </Alert>
            )}
          </form>
        )}

        {uploadMode === 'zip' && (
          <form id={ZIP_FORM_ID} className="documents-stack" onSubmit={handleZipUploadSubmit}>
            <Field
              label={<>컬렉션 <span className="documents-text-danger">*</span></>}
            >
              {(id) => (
                <Select
                  id={id}
                  value={uploadCollectionId}
                  onChange={(e) => { setUploadCollectionId(e.target.value); setUploadWorkflowId('') }}
                  required
                >
                  <option value="">컬렉션을 선택하세요</option>
                  {collectionsData?.map((c) => (
                    <option key={c.id} value={c.id}>{c.name}</option>
                  ))}
                </Select>
              )}
            </Field>

            {uploadCollectionId && (
              <Field label="전처리 워크플로우">
                {(id) => (
                  <Select id={id} value={uploadWorkflowId} onChange={(e) => setUploadWorkflowId(e.target.value)}>
                    <option value="">컬렉션 기본값 사용</option>
                    {workflowOptions.map((wf) => (
                      <option key={wf.id} value={wf.id}>{wf.name}</option>
                    ))}
                  </Select>
                )}
              </Field>
            )}

            <div className="ds-field">
              <span className="ds-field__label">ZIP 파일 <span className="documents-text-danger">*</span></span>
              <Button
                    variant="secondary"
                    className="documents-dropzone"
                    icon={<Upload size={16} />}
                    onClick={() => zipFileRef.current?.click()}
                  >
                    {zipFile ? zipFile.name : 'ZIP 파일 선택 (.zip)'}
                  </Button>
                  <input
                    ref={zipFileRef}
                    type="file"
                    hidden
                    accept=".zip"
                    aria-label="업로드할 ZIP 파일"
                    onChange={(e) => {
                      setZipFile(e.target.files?.[0] ?? null)
                      setZipResult(null)
                    }}
                  />
                  <p className="documents-note">
                    ZIP 안의 PDF/HWP/HWPX/DOCX 파일을 자동으로 추출해 개별 문서로 등록합니다.
                    지원하지 않는 형식이나 중복 파일은 건너뜁니다.
                  </p>
            </div>

            <label className="documents-check">
              <input type="checkbox" checked={newDocument} onChange={(e) => setNewDocument(e.target.checked)} />
              <span>이름이 같아도 새 문서로 올리기</span>
            </label>

            {zipResult && (
              <div className="documents-stack" style={{ fontSize: 'var(--text-sm)' }}>
                <strong>총 {zipResult.total_entries}개 중 {zipResult.queued}개 등록됨</strong>
                <div className="documents-zip-list">
                  {zipResult.results.map((r, i) => (
                    <div key={`${r.filename}-${i}`} className="documents-file-row" title={r.detail ?? undefined}>
                      <span className="documents-ellipsis">{r.filename}</span>
                      <Badge tone={ZIP_STATUS_TONE[r.status] ?? 'neutral'}>{ZIP_STATUS_LABEL[r.status]}</Badge>
                    </div>
                  ))}
                </div>
                {zipResult.results
                  .filter((r) => versionNoticeFor(r.version_number))
                  .map((r, i) => (
                    <p key={`version-${r.filename}-${i}`} className="documents-text-accent" style={{ margin: 0 }}>
                      {r.filename}: {versionNoticeFor(r.version_number)}
                    </p>
                  ))}
              </div>
            )}
          </form>
        )}
      </div>
    </Modal>
  )
}
