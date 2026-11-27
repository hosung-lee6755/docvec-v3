import { useRef, useState } from 'react'
import { X } from 'lucide-react'
import { FileDropzone } from './FileDropzone'
import { DocumentTypeField } from './DocumentTypeField'
import { DOCUMENT_EXTENSIONS, ZIP_EXTENSIONS } from '../../lib/uploadFormats'
import { useUploadDocument, useUploadZip, type BulkUploadResponse } from '../../hooks/useDocuments'
import { useCollections } from '../../hooks/useCollections'
import { useWorkflows, useWorkflowVersions } from '../../hooks/useWorkflows'
import { Alert, Badge, Button, Field, IconButton, Modal, Select, Spinner, Tabs } from '../ui'
import type { BadgeTone } from '../ui'
import { describeError } from '../../lib/apiError'
import { workflowsForProject } from '../../lib/workflowScope'
import {
  DOCUMENT_TYPE_HINT, DOCUMENT_TYPE_OPTIONS, documentTypeLabel, resolveUploadDocumentType,
} from '../../lib/documentTypes'
import '../../styles/screens/documents.css'

interface UploadModalProps {
  isOpen: boolean
  onClose: () => void
  // 여러 파일을 올리고 모달이 닫힐 때, 새 버전으로 묶인 파일이 있으면 그 안내를 부모가 보여준다.
  onUploaded?: (message: string) => void
  // 프로젝트 문서 화면에서 열면 그 프로젝트의 컬렉션만 고른다. 없으면(전체 문서 화면) 모든 컬렉션이다(2026-11-24)
  projectId?: string | null
  // 컬렉션에서 들어온 문서 화면(?collection=)이면 그 컬렉션을 미리 골라 둔다. 바꿀 수는 있다(2026-11-24)
  defaultCollectionId?: string
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

const rejectedNotice = (rejected: File[]) =>
  rejected.length ? `올릴 수 없는 파일이라 뺐습니다: ${rejected.map((f) => f.name).join(', ')}` : null

const FILES_FORM_ID = 'upload-files-form'
const ZIP_FORM_ID = 'upload-zip-form'

export function UploadModal({
  isOpen,
  onClose,
  onUploaded,
  projectId,
  defaultCollectionId = '',
}: UploadModalProps) {
  const fileRef = useRef<HTMLInputElement>(null)
  const zipFileRef = useRef<HTMLInputElement>(null)

  const [uploadCollectionId, setUploadCollectionId] = useState(defaultCollectionId)
  const [uploadWorkflowId, setUploadWorkflowId] = useState('')
  const [analysisWorkflowId, setAnalysisWorkflowId] = useState('')
  const [skipReview, setSkipReview] = useState(false)
  const [selectedFiles, setSelectedFiles] = useState<File[]>([])
  // 문서 유형: 업로드 전체에 하나(batch), 파일마다 바꾼 값(fileTypes, selectedFiles 와 같은 순서). 빈 값은 자동이다
  const [batchDocumentType, setBatchDocumentType] = useState('')
  const [fileTypes, setFileTypes] = useState<string[]>([])
  const [uploadProgress, setUploadProgress] = useState<{ name: string; status: UploadRowStatus; error?: string }[]>([])
  const [isBatchUploading, setIsBatchUploading] = useState(false)
  const [uploadMode, setUploadMode] = useState<UploadMode>('files')
  const [zipFile, setZipFile] = useState<File | null>(null)
  const [zipResult, setZipResult] = useState<BulkUploadResponse | null>(null)
  const [newDocument, setNewDocument] = useState(false)
  const [dropNotice, setDropNotice] = useState<string | null>(null)

  const upload = useUploadDocument()
  const uploadZip = useUploadZip()
  const { data: collectionsDataFull } = useCollections(projectId)
  const collectionsData = collectionsDataFull?.items
  const selectedUploadCollection = collectionsData?.find((c) => c.id === uploadCollectionId)
  const uploadProjectId = selectedUploadCollection?.project_id ?? null
  const { data: uploadProjectWorkflowsData } = useWorkflows(uploadProjectId, 'PREPROCESS')
  const uploadProjectWorkflows = uploadProjectWorkflowsData?.items
  const { data: analysisWorkflowsData } = useWorkflows(uploadProjectId, 'ANALYSIS')
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
    setUploadCollectionId(defaultCollectionId)
    setUploadWorkflowId('')
    setAnalysisWorkflowId('')
    setSkipReview(false)
    setSelectedFiles([])
    setBatchDocumentType('')
    setFileTypes([])
    setUploadProgress([])
    setIsBatchUploading(false)
    setUploadMode('files')
    setZipFile(null)
    setZipResult(null)
    setNewDocument(false)
    setDropNotice(null)
    if (fileRef.current) fileRef.current.value = ''
    if (zipFileRef.current) zipFileRef.current.value = ''
  }

  const removeSelectedFile = (index: number) => {
    setSelectedFiles((prev) => prev.filter((_, i) => i !== index))
    setFileTypes((prev) => prev.filter((_, i) => i !== index))
  }

  const addFiles = (files: File[]) => {
    setSelectedFiles((prev) => [...prev, ...files])
    setFileTypes((prev) => [...prev, ...files.map(() => '')])
  }

  const setFileType = (index: number, value: string) => {
    setFileTypes((prev) => prev.map((t, i) => (i === index ? value : t)))
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
        analysis_workflow_id: analysisWorkflowId || undefined,
        document_type: batchDocumentType || undefined,
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
          detail: describeError(err, 'ZIP 파일을 올리지 못했습니다.'),
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
          analysis_workflow_id: analysisWorkflowId || undefined,
          document_type: resolveUploadDocumentType(fileTypes[i], batchDocumentType),
        })
        const notice = versionNoticeFor(result.version_number)
        if (notice) versionNotices.push(`${selectedFiles[i].name}: ${notice}`)
        successCount++
        setUploadProgress((prev) => prev.map((p, idx) => (idx === i ? { ...p, status: 'success' } : p)))
      } catch (err) {
        const message = describeError(err, '올리지 못했습니다.')
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
  // 업로드할 컬렉션과 같은 프로젝트의 워크플로우만 고른다. 개인 컬렉션은 표준 전처리만 쓴다(2026-11-20)
  const workflowOptions = workflowsForProject(uploadProjectWorkflows, uploadProjectId)
  const analysisOptions = workflowsForProject(analysisWorkflowsData?.items, uploadProjectId)
  // 컬렉션을 바꾸면 프로젝트가 달라질 수 있어 고른 워크플로우를 비운다
  const selectCollection = (collectionId: string) => {
    setUploadCollectionId(collectionId)
    setUploadWorkflowId('')
    setAnalysisWorkflowId('')
  }

  // 전처리가 끝나면 분석 워크플로우가 이어서 돈다. 고르지 않으면 컬렉션 기본 분석(없으면 표준 분석)이다(2026-11-24)
  const workflowFields = (
    <>
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
      <Field label="분석 워크플로우">
        {(id) => (
          <Select id={id} value={analysisWorkflowId} onChange={(e) => setAnalysisWorkflowId(e.target.value)}>
            <option value="">컬렉션 기본값 사용</option>
            {analysisOptions.map((wf) => (
              <option key={wf.id} value={wf.id}>{wf.name}</option>
            ))}
          </Select>
        )}
      </Field>
    </>
  )

  // 컬렉션 기본 유형이 있으면 "자동"이 그 값을 따른다는 것을 알린다
  const collectionTypeLabel = documentTypeLabel(selectedUploadCollection?.default_document_type)
  const autoTypeLabel = collectionTypeLabel ? `컬렉션 기본값 (${collectionTypeLabel})` : '자동 판별'
  const documentTypeField = (
    <DocumentTypeField
      value={batchDocumentType}
      onChange={setBatchDocumentType}
      autoLabel={autoTypeLabel}
      hint={isMultiUpload ? `${DOCUMENT_TYPE_HINT} 파일마다 다르면 아래 목록에서 그 파일만 바꾸세요.` : DOCUMENT_TYPE_HINT}
    />
  )

  const collectionMissingHint =!collectionsData?.length ? '컬렉션이 없습니다. 먼저 컬렉션을 생성하세요.' : undefined

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
                  onChange={(e) => selectCollection(e.target.value)}
                  required
                >
                  <option value="">컬렉션을 선택하세요</option>
                  {collectionsData?.map((c) => (
                    <option key={c.id} value={c.id}>{c.name}</option>
                  ))}
                </Select>
              )}
            </Field>

            {uploadCollectionId && workflowFields}
            {documentTypeField}

            <div className="ds-field">
              <span className="ds-field__label">파일 <span className="documents-text-danger">*</span></span>
              <FileDropzone
                    testId="upload-dropzone"
                    extensions={DOCUMENT_EXTENSIONS}
                    isMultiple
                    onClick={() => fileRef.current?.click()}
                    onFiles={(accepted, rejected) => {
                      addFiles(accepted)
                      setDropNotice(rejectedNotice(rejected))
                    }}
                  >
                    {selectedFiles.length > 0 ? `${selectedFiles.length}개 파일 선택됨 (추가 선택)` : '파일 선택 (PDF, HWP, HWPX, DOCX, XLSX, CSV, PPTX, TXT, MD, HTML, 이미지)'}
                  </FileDropzone>
                  {dropNotice && <p role="status" className="documents-text-danger documents-drop-notice">{dropNotice}</p>}
                  <input
                    ref={fileRef}
                    type="file"
                    hidden
                    multiple
                    accept={DOCUMENT_EXTENSIONS.join(',')}
                    aria-label="업로드할 파일"
                    onChange={(e) => {
                      addFiles(Array.from(e.target.files ?? []))
                      if (fileRef.current) fileRef.current.value = ''
                    }}
                  />
                  {selectedFiles.length > 0 && (
                    <div className="documents-file-list">
                      {selectedFiles.map((f, i) => {
                        const progress = uploadProgress[i]
                        return (
                          <div key={`${f.name}-${i}`} className="documents-file-row" style={progress?.error ? { flexWrap: 'wrap' } : undefined}>
                            <span className="documents-ellipsis" title={progress?.error}>{f.name}</span>
                            {/* 여러 파일 가운데 일부만 유형이 다르면 그 파일만 바꾼다. 기본은 위에서 고른 전체 유형이다 */}
                            {isMultiUpload && !progress && (
                              <select
                                className="documents-file-type"
                                aria-label={`${f.name} 문서 유형`}
                                value={fileTypes[i] ?? ''}
                                onChange={(e) => setFileType(i, e.target.value)}
                              >
                                <option value="">전체 설정 따름</option>
                                {DOCUMENT_TYPE_OPTIONS.map((o) => (
                                  <option key={o.value} value={o.value}>{o.label}</option>
                                ))}
                              </select>
                            )}
                            {progress?.status === 'success' && <span className="documents-text-success" aria-label="성공">✓</span>}
                            {progress?.status === 'error' && <span className="documents-text-danger" title={progress.error} aria-label="실패">✕</span>}
                            {progress?.status === 'pending' && isBatchUploading && <Spinner size={12} />}
                            {!progress && (
                              <IconButton label={`${f.name} 목록에서 빼기`} onClick={() => removeSelectedFile(i)}>
                                <X size={12} />
                              </IconButton>
                            )}
                            {progress?.status === 'error' && progress.error && (
                              <span className="documents-text-danger" style={{ flexBasis: '100%', fontSize: 'var(--text-xs)' }}>{progress.error}</span>
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
                  onChange={(e) => selectCollection(e.target.value)}
                  required
                >
                  <option value="">컬렉션을 선택하세요</option>
                  {collectionsData?.map((c) => (
                    <option key={c.id} value={c.id}>{c.name}</option>
                  ))}
                </Select>
              )}
            </Field>

            {uploadCollectionId && workflowFields}
            {documentTypeField}

            <div className="ds-field">
              <span className="ds-field__label">ZIP 파일 <span className="documents-text-danger">*</span></span>
              <FileDropzone
                    testId="upload-zip-dropzone"
                    extensions={ZIP_EXTENSIONS}
                    onClick={() => zipFileRef.current?.click()}
                    onFiles={(accepted, rejected) => {
                      if (accepted[0]) {
                        setZipFile(accepted[0])
                        setZipResult(null)
                      }
                      setDropNotice(rejectedNotice(rejected))
                    }}
                  >
                    {zipFile ? zipFile.name : 'ZIP 파일 선택 (.zip)'}
                  </FileDropzone>
                  {dropNotice && <p role="status" className="documents-text-danger documents-drop-notice">{dropNotice}</p>}
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
                    ZIP 안에서 개별 업로드와 같은 형식(PDF, HWP, DOCX, XLSX, CSV 등)의 파일을 꺼내 각각 문서로 등록합니다.
                    지원하지 않는 형식이나 중복 파일은 건너뜁니다. 문서 유형은 ZIP 안의 모든 파일에 같이 적용됩니다.
                    파일마다 다르게 하려면 개별 파일로 올리거나, 올린 뒤 문서 화면에서 바꾸고 재처리하세요.
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
                    <div key={`${r.filename}-${i}`} className="documents-file-row" title={r.detail ?? undefined} style={r.detail && r.status !== 'queued' ? { flexWrap: 'wrap' } : undefined}>
                      <span className="documents-ellipsis">{r.filename}</span>
                      <Badge tone={ZIP_STATUS_TONE[r.status] ?? 'neutral'}>{ZIP_STATUS_LABEL[r.status]}</Badge>
                      {r.detail && r.status !== 'queued' && (
                        <span className={r.status === 'failed' ? 'documents-text-danger' : 'wf-muted'} style={{ flexBasis: '100%', fontSize: 'var(--text-xs)' }}>{r.detail}</span>
                      )}
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
