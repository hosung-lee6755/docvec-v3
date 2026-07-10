import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { ArrowLeft, CheckCircle2, Circle, Download, Loader2, Save, X, XCircle } from 'lucide-react'
import { useDeleteChunk, useDocument, useDocumentChunks, useDocumentContent, useDocumentImages, useDocumentPagesText, useDocumentPreview, useDocumentRevisions, useDocumentTables, useDownloadDocument, useProceedDocument, useReprocessDocument, useRestoreRevision, useRetryDocument, useUpdateChunk, useUpdateDocumentTags } from '../hooks/useDocuments'
import { useProcessingJobs } from '../hooks/useProcessingJobs'

type TabKey = 'summary' | 'edit' | 'tables' | 'images' | 'chunks' | 'original'

const TABS: { key: TabKey; label: string; pdfOnly?: boolean }[] = [
  { key: 'summary', label: '문서 요약 결과' },
  { key: 'original', label: '원문 대조' },
  { key: 'chunks', label: '청크' },
  { key: 'tables', label: '표' },
  { key: 'images', label: '그림' },
  { key: 'edit', label: 'RAG 데이터 수정' },
]

const REVISION_SOURCE_LABELS: Record<string, string> = {
  PARSE: '자동 파싱',
  REVIEW_EDIT: '검토 단계 수정',
  RAG_EDIT: 'RAG 데이터 수정',
  RESTORE: '이력 복원',
}

function toBlocksJson(text: string): string {
  const blocks = text.split('\n\n').filter((b) => b.trim().length > 0)
  return JSON.stringify({ blocks }, null, 2)
}

function ViewModeToggle({ showJson, onChange }: { showJson: boolean; onChange: (v: boolean) => void }) {
  return (
    <div style={{ display: 'inline-flex', gap: 4, marginBottom: 'var(--space-3)' }}>
      {[{ v: false, label: '텍스트' }, { v: true, label: 'JSON' }].map((opt) => (
        <button
          key={String(opt.v)}
          onClick={() => onChange(opt.v)}
          className={showJson === opt.v ? 'krds-btn primary small' : 'krds-btn secondary small'}
          style={{ cursor: 'pointer' }}
        >
          {opt.label}
        </button>
      ))}
    </div>
  )
}

const JOB_TYPE_LABELS: Record<string, string> = {
  INGEST: '파일 수신',
  PARSE: '텍스트 추출',
  CHUNK: '청킹',
  EMBED: '임베딩',
  UPLOAD: '벡터DB 업로드',
}

const STATUS_BADGE_CLASSES: Record<string, string> = {
  QUEUED: 'krds-badge small bg-gray',
  INDEXED: 'krds-badge small bg-success',
  FAILED: 'krds-badge small bg-danger',
  INGESTING: 'krds-badge small bg-information',
  PARSING: 'krds-badge small bg-information',
  STRUCTURING: 'krds-badge small bg-information',
  NORMALIZING: 'krds-badge small bg-information',
  CHUNKING: 'krds-badge small bg-information',
  EMBEDDING: 'krds-badge small bg-information',
  UPLOADING: 'krds-badge small bg-information',
  REVIEW_PENDING: 'krds-badge small bg-warning',
  REFINING: 'krds-badge small bg-warning',
  CANCELLED: 'krds-badge small bg-gray',
}

const STATUS_LABELS: Record<string, string> = {
  QUEUED: '대기', INDEXED: '완료', FAILED: '실패',
  INGESTING: '처리중', PARSING: '파싱중', STRUCTURING: '구조화',
  NORMALIZING: '정규화', CHUNKING: '청킹', EMBEDDING: '임베딩',
  UPLOADING: '업로드', REVIEW_PENDING: '검토대기', REFINING: '정제중',
  CANCELLED: '취소',
}

const PROCESSING_STATUSES = new Set([
  'QUEUED', 'INGESTING', 'PARSING', 'STRUCTURING',
  'NORMALIZING', 'CHUNKING', 'EMBEDDING', 'UPLOADING',
])

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: '140px 1fr',
      padding: 'var(--space-3) 0',
      borderBottom: '1px solid var(--color-border)',
    }}>
      <span style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>{label}</span>
      <span style={{ fontSize: 13 }}>{children}</span>
    </div>
  )
}

export default function DocumentDetailPage() {
  const { id = '', projectId } = useParams<{ id: string; projectId?: string }>()
  const navigate = useNavigate()
  const backTo = projectId ? `/projects/${projectId}/documents` : '/documents'
  const { data: doc, isLoading, isError } = useDocument(id)
  const [activeTab, setActiveTab] = useState<TabKey>('summary')
  const needsContent = activeTab === 'edit' || activeTab === 'original'
  const { data: content, isLoading: isContentLoading, isError: isContentError } = useDocumentContent(id, needsContent)
  const { data: tablesResult, isLoading: isTablesLoading, isError: isTablesError } = useDocumentTables(id, activeTab === 'tables')
  const { data: imagesResult, isLoading: isImagesLoading, isError: isImagesError } = useDocumentImages(id, activeTab === 'images')
  const { data: chunksResult, isLoading: isChunksLoading, isError: isChunksError } = useDocumentChunks(id, activeTab === 'chunks')
  const { data: previewResult, isError: isPreviewError } = useDocumentPreview(id, activeTab === 'original')
  const { data: pagesTextResult } = useDocumentPagesText(id, activeTab === 'original')
  const [originalPage, setOriginalPage] = useState(1)
  const { data: revisionsResult } = useDocumentRevisions(id, activeTab === 'edit')
  const download = useDownloadDocument()
  const proceed = useProceedDocument()
  const reprocess = useReprocessDocument()
  const updateChunk = useUpdateChunk()
  const deleteChunk = useDeleteChunk()
  const restoreRevision = useRestoreRevision()
  const retryDoc = useRetryDocument()
  const updateTags = useUpdateDocumentTags()
  const [chunkEditId, setChunkEditId] = useState<string | null>(null)
  const [chunkEditText, setChunkEditText] = useState('')
  const [tagInput, setTagInput] = useState('')
  const [reviewTextOverride, setReviewTextOverride] = useState<string | null>(null)
  const reviewText = reviewTextOverride ?? doc?.parsed_text ?? ''
  const [editedContent, setEditedContent] = useState('')
  const [editBaseline, setEditBaseline] = useState<string | null>(null)
  const [showJson, setShowJson] = useState(false)
  const isPdfDoc = doc?.original_filename?.toLowerCase().endsWith('.pdf') ?? false

  useEffect(() => {
    if (activeTab === 'edit' && content && editBaseline === null) {
      setEditedContent(content.full_text)
      setEditBaseline(content.full_text)
    }
  }, [activeTab, content, editBaseline])

  const isProcessing = doc && PROCESSING_STATUSES.has(doc.status)
  const { data: jobsData } = useProcessingJobs(id, !!isProcessing)
  const isIndexed = doc?.status === 'INDEXED'

  const handleDownload = () => {
    download.mutate(id, {
      onSuccess: (url) => window.open(url, '_blank', 'noopener,noreferrer'),
    })
  }

  if (isLoading) {
    return (
      <div style={{ padding: 'var(--space-8)', color: 'var(--color-text-muted)' }}>
        로딩 중...
      </div>
    )
  }

  if (isError || !doc) {
    return (
      <div>
        <button onClick={() => navigate(backTo)} className="krds-btn text small" style={{ marginBottom: 'var(--space-4)' }}>
          <ArrowLeft size={16} /> 문서 목록
        </button>
        <p style={{ color: '#dc2626' }}>문서를 불러올 수 없습니다.</p>
      </div>
    )
  }

  return (
    <div>
      <style>{`
        @keyframes spin { to { transform: rotate(360deg) } }
        .icon-btn-download {
          display: inline-flex; align-items: center; justify-content: center;
          width: 32px; height: 32px; border-radius: 50%;
          background: transparent; border: none; padding: 0;
          color: var(--color-text-muted); flex-shrink: 0;
          transition: background-color 0.15s ease, color 0.15s ease;
        }
        .icon-btn-download:hover:not(:disabled) {
          background: #eef2f7; color: var(--color-accent);
        }
        .icon-btn-download:disabled { cursor: not-allowed; opacity: 0.5; }
      `}</style>
      <button onClick={() => navigate(backTo)} className="krds-btn text small" style={{ marginBottom: 'var(--space-4)', display: 'inline-flex', alignItems: 'center', gap: 6, background: 'none', border: 'none', cursor: 'pointer', color: 'var(--color-text-muted)', fontSize: 14, padding: 0 }}>
        <ArrowLeft size={16} /> 문서 목록
      </button>

      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', marginBottom: 'var(--space-6)' }}>
        <h1 style={{ fontSize: 22, fontWeight: 700, wordBreak: 'break-all', margin: 0 }}>
          {doc.original_filename}
        </h1>
        {isIndexed && (
          <button
            onClick={handleDownload}
            disabled={download.isPending}
            title="원본 다운로드"
            aria-label="원본 다운로드"
            className="icon-btn-download"
          >
            {download.isPending
              ? <Loader2 size={16} style={{ animation: 'spin 1s linear infinite' }} />
              : <Download size={16} />}
          </button>
        )}
      </div>

      <div style={{
        display: 'grid',
        gridTemplateColumns: isIndexed ? 'minmax(280px, 360px) 1fr' : '1fr',
        gap: 'var(--space-8)',
        alignItems: 'start',
      }}>
      <div>
      <div style={{ maxWidth: 640 }}>
        <Row label="상태">
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
            <span className={STATUS_BADGE_CLASSES[doc.status] ?? 'krds-badge small bg-gray'}>
              {STATUS_LABELS[doc.status] ?? doc.status}
            </span>
            {isProcessing && (
              <span style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
                처리 중... (자동 갱신)
              </span>
            )}
          </span>
        </Row>
        <Row label="파일 크기">{(doc.file_size / 1024).toFixed(1)} KB</Row>
        <Row label="생성일">{new Date(doc.created_at).toLocaleString('ko-KR')}</Row>
        <Row label="수정일">{new Date(doc.updated_at).toLocaleString('ko-KR')}</Row>
        <Row label="태그">
          <span style={{ display: 'inline-flex', flexWrap: 'wrap', gap: 6, alignItems: 'center' }}>
            {(doc.tags ?? []).map((tag) => (
              <span key={tag} className="krds-badge small bg-information" style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                {tag}
                <button
                  onClick={() => updateTags.mutate({ docId: id, tags: (doc.tags ?? []).filter((t) => t !== tag) })}
                  aria-label={`태그 ${tag} 삭제`}
                  style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0, color: 'inherit', lineHeight: 1 }}
                >
                  ×
                </button>
              </span>
            ))}
            <input
              value={tagInput}
              onChange={(e) => setTagInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && tagInput.trim()) {
                  const next = [...new Set([...(doc.tags ?? []), tagInput.trim()])]
                  updateTags.mutate({ docId: id, tags: next })
                  setTagInput('')
                }
              }}
              placeholder="태그 입력 후 Enter"
              style={{ fontSize: 12, border: '1px solid #e2e8f0', borderRadius: 4, padding: '2px 8px', width: 130 }}
            />
          </span>
        </Row>
      </div>

      {!!jobsData?.items.length && (
        <div style={{ marginTop: 'var(--space-6)', maxWidth: 640 }}>
          <h2 style={{ fontSize: 14, fontWeight: 600, marginBottom: 'var(--space-3)' }}>
            전처리 단계
          </h2>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
            {jobsData.items.map((job) => (
              <div key={job.id} style={{
                display: 'flex', alignItems: 'flex-start', gap: 'var(--space-3)',
                padding: 'var(--space-2) var(--space-3)', background: '#fff',
                border: '1px solid #e2e8f0', borderRadius: 'var(--radius-md)',
              }}>
                <span style={{ marginTop: 2 }}>
                  {job.status === 'COMPLETED' && <CheckCircle2 size={16} color="#22c55e" />}
                  {job.status === 'FAILED' && <XCircle size={16} color="#dc2626" />}
                  {job.status === 'RUNNING' && <Loader2 size={16} color="var(--color-accent)" style={{ animation: 'spin 1s linear infinite' }} />}
                  {job.status === 'PENDING' && <Circle size={16} color="var(--color-text-muted)" />}
                </span>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 13, fontWeight: 500 }}>
                    {JOB_TYPE_LABELS[job.job_type] ?? job.job_type}
                  </div>
                  <div style={{ fontSize: 12, color: job.status === 'FAILED' ? '#dc2626' : 'var(--color-text-muted)' }}>
                    {job.status === 'FAILED' ? job.error_message : job.result_summary ?? '진행 중...'}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {doc.status === 'REVIEW_PENDING' && (
        <div style={{ marginTop: 'var(--space-6)', maxWidth: 800 }}>
          <h2 style={{ fontSize: 14, fontWeight: 600, marginBottom: 'var(--space-2)' }}>
            파싱 결과 검토
          </h2>
          <p style={{ fontSize: 12, color: 'var(--color-text-muted)', marginBottom: 'var(--space-3)' }}>
            텍스트를 확인하고 필요하면 수정한 뒤 다음 단계로 진행하세요. 진행하면 이 텍스트 기준으로 청킹과 임베딩이 실행됩니다.
          </p>
          <ViewModeToggle showJson={showJson} onChange={setShowJson} />
          {showJson ? (
            <pre style={{
              width: '100%', boxSizing: 'border-box', fontSize: 12, lineHeight: 1.6,
              fontFamily: 'monospace', color: '#1e2124', background: '#f8fafc',
              border: '1px solid #e2e8f0', borderRadius: 'var(--radius-sm)',
              padding: 'var(--space-3)', maxHeight: 400, overflow: 'auto',
              whiteSpace: 'pre-wrap', wordBreak: 'break-word', marginBottom: 'var(--space-3)',
            }}>
              {toBlocksJson(reviewText)}
            </pre>
          ) : (
            <div className="textarea-wrap" style={{ marginBottom: 'var(--space-3)' }}>
              <textarea
                className="krds-input"
                value={reviewText}
                onChange={(e) => setReviewTextOverride(e.target.value)}
                rows={16}
                style={{
                  width: '100%', boxSizing: 'border-box', fontSize: 13, lineHeight: 1.7,
                  fontFamily: 'inherit', color: '#1e2124', resize: 'vertical',
                }}
              />
            </div>
          )}
          {proceed.isError && (
            <p style={{ color: '#dc2626', fontSize: 13, marginBottom: 'var(--space-3)' }}>
              처리를 재개하지 못했습니다.
            </p>
          )}
          <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
            <button
              onClick={() => proceed.mutate({ id, editedText: reviewText })}
              disabled={proceed.isPending}
              className="krds-btn primary medium"
              style={{
                display: 'flex', alignItems: 'center', gap: 'var(--space-2)',
                cursor: proceed.isPending ? 'not-allowed' : 'pointer',
                opacity: proceed.isPending ? 0.7 : 1,
              }}
            >
              {proceed.isPending && <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} />}
              다음 단계로 진행
            </button>
          </div>
        </div>
      )}

      {doc.status === 'FAILED' && (
        <div style={{
          marginTop: 'var(--space-6)',
          padding: 'var(--space-4)',
          background: '#fef2f2',
          border: '1px solid #fecaca',
          borderRadius: 'var(--radius-md)',
          maxWidth: 640,
        }}>
          <h2 style={{ fontSize: 14, fontWeight: 600, color: '#dc2626', marginBottom: 'var(--space-2)' }}>
            오류 정보
          </h2>
          <pre style={{
            fontSize: 12,
            color: '#dc2626',
            fontFamily: 'monospace',
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-all',
            margin: 0,
          }}>
            {doc.error_message ?? '오류 메시지 없음'}
          </pre>
          <div style={{ marginTop: 'var(--space-3)', display: 'flex', justifyContent: 'flex-end' }}>
            <button
              onClick={() => retryDoc.mutate(id)}
              disabled={retryDoc.isPending}
              className="krds-btn primary small"
              style={{ display: 'inline-flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}
            >
              {retryDoc.isPending && <Loader2 size={13} style={{ animation: 'spin 1s linear infinite' }} />}
              처리 재시도
            </button>
          </div>
        </div>
      )}
      </div>

      {isIndexed && (
        <div>
          <div style={{ display: 'flex', gap: 'var(--space-1)', borderBottom: '1px solid var(--color-border)', marginBottom: 'var(--space-4)' }}>
            {TABS.filter((t) => !t.pdfOnly || isPdfDoc).map((t) => (
              <button
                key={t.key}
                onClick={() => setActiveTab(t.key)}
                style={{
                  padding: '10px 16px', fontSize: 13, fontWeight: 600, background: 'none', border: 'none',
                  borderBottom: activeTab === t.key ? '2px solid var(--color-accent)' : '2px solid transparent',
                  color: activeTab === t.key ? 'var(--color-accent)' : 'var(--color-text-muted)',
                  cursor: 'pointer', marginBottom: -1,
                }}
              >
                {t.label}
              </button>
            ))}
          </div>

          <div style={{
            display: 'flex', flexDirection: 'column', height: 560,
            background: '#fff', border: '1px solid #e2e8f0',
            borderRadius: 'var(--radius-md)', overflow: 'hidden',
          }}>
            <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: 'var(--space-5)' }}>
              {activeTab === 'summary' && (
                <>
                  {(doc.summary_status === 'PENDING' || doc.summary_status === 'GENERATING') && (
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--color-text-muted)', fontSize: 13 }}>
                      <Loader2 size={16} style={{ animation: 'spin 1s linear infinite' }} />
                      문서 요약을 생성하는 중입니다...
                    </div>
                  )}
                  {doc.summary_status === 'FAILED' && (
                    <p style={{ color: 'var(--color-text-muted)', fontSize: 13, margin: 0 }}>
                      요약을 생성하지 못했습니다.
                    </p>
                  )}
                  {doc.summary_status === 'DONE' && (
                    <p style={{ fontSize: 14, lineHeight: 1.8, whiteSpace: 'pre-wrap', margin: 0 }}>
                      {doc.summary || '요약 내용이 없습니다.'}
                    </p>
                  )}
                </>
              )}

              {activeTab === 'edit' && (
                <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
                  {isContentLoading && (
                    <div style={{ display: 'flex', justifyContent: 'center', padding: 'var(--space-6)' }}>
                      <Loader2 size={20} style={{ animation: 'spin 1s linear infinite', color: 'var(--color-text-muted)' }} />
                    </div>
                  )}
                  {!isContentLoading && isContentError && (
                    <p style={{ color: '#dc2626', fontSize: 13, margin: 0 }}>
                      본문을 불러오는 중 오류가 발생했습니다.
                    </p>
                  )}
                  {!isContentLoading && !isContentError && content && content.chunk_count === 0 && (
                    <p style={{ color: 'var(--color-text-muted)', fontSize: 13, margin: 0 }}>
                      본문을 불러올 수 없습니다.
                    </p>
                  )}
                  {!isContentLoading && content && content.chunk_count > 0 && (
                    <>
                      <p style={{ fontSize: 12, color: 'var(--color-text-muted)', margin: '0 0 var(--space-3)', flexShrink: 0 }}>
                        불필요한 부분을 제거하거나 수정한 뒤 저장하면, 이 텍스트를 기준으로 청킹·임베딩이 다시 실행되어 기존 검색 결과를 대체하고 요약도 새로 생성됩니다.
                      </p>
                      <details style={{ flexShrink: 0, marginBottom: 'var(--space-3)', fontSize: 12 }}>
                        <summary style={{ cursor: 'pointer', color: 'var(--color-text-muted)', userSelect: 'none' }}>
                          변경 이력 ({revisionsResult?.revisions.length ?? 0})
                        </summary>
                        <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 6, maxHeight: 200, overflowY: 'auto' }}>
                          {(revisionsResult?.revisions ?? []).map((rev, i) => (
                            <div key={rev.id} style={{
                              display: 'flex', gap: 10, alignItems: 'center',
                              border: '1px solid #e2e8f0', borderRadius: 6, padding: '6px 10px',
                            }}>
                              <span style={{ flexShrink: 0, fontWeight: 600 }}>
                                {REVISION_SOURCE_LABELS[rev.source] ?? rev.source}
                              </span>
                              <span style={{ flexShrink: 0, color: 'var(--color-text-muted)' }}>
                                {new Date(rev.created_at).toLocaleString('ko-KR')} · {rev.text_length.toLocaleString()}자
                              </span>
                              <span style={{
                                flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis',
                                whiteSpace: 'nowrap', color: 'var(--color-text-muted)',
                              }}>
                                {rev.preview}
                              </span>
                              {i !== 0 && (
                                <button
                                  onClick={() => {
                                    if (window.confirm('이 버전의 텍스트로 되돌리고 다시 청킹·임베딩할까요?')) {
                                      restoreRevision.mutate({ docId: id, revisionId: rev.id })
                                    }
                                  }}
                                  disabled={restoreRevision.isPending}
                                  className="krds-btn secondary small"
                                  style={{ flexShrink: 0, cursor: 'pointer' }}
                                >
                                  복원
                                </button>
                              )}
                            </div>
                          ))}
                          {!revisionsResult?.revisions.length && (
                            <span style={{ color: 'var(--color-text-muted)' }}>기록된 이력이 없습니다.</span>
                          )}
                        </div>
                      </details>
                      <div style={{ flexShrink: 0 }}>
                        <ViewModeToggle showJson={showJson} onChange={setShowJson} />
                      </div>
                      {showJson ? (
                        <pre style={{
                          flex: 1, minHeight: 0, overflow: 'auto', fontSize: 12, lineHeight: 1.6,
                          fontFamily: 'monospace', color: '#1e2124', background: '#f8fafc',
                          border: '1px solid #e2e8f0', borderRadius: 'var(--radius-sm)',
                          padding: 'var(--space-3)', whiteSpace: 'pre-wrap', wordBreak: 'break-word', margin: 0,
                        }}>
                          {toBlocksJson(editedContent)}
                        </pre>
                      ) : (
                        <div className="textarea-wrap" style={{ flex: 1, minHeight: 0 }}>
                          <textarea
                            className="krds-input"
                            value={editedContent}
                            onChange={(e) => setEditedContent(e.target.value)}
                            style={{
                              width: '100%', height: '100%', boxSizing: 'border-box', fontSize: 13, lineHeight: 1.7,
                              fontFamily: 'inherit', color: '#1e2124', resize: 'none',
                            }}
                          />
                        </div>
                      )}
                      {reprocess.isError && (
                        <p style={{ color: '#dc2626', fontSize: 13, marginTop: 'var(--space-3)', flexShrink: 0 }}>
                          재처리를 시작하지 못했습니다.
                        </p>
                      )}
                    </>
                  )}
                </div>
              )}

              {activeTab === 'tables' && (
                <>
                  {isTablesLoading && (
                    <div style={{ display: 'flex', justifyContent: 'center', padding: 'var(--space-6)' }}>
                      <Loader2 size={20} style={{ animation: 'spin 1s linear infinite', color: 'var(--color-text-muted)' }} />
                    </div>
                  )}
                  {!isTablesLoading && isTablesError && (
                    <p style={{ color: '#dc2626', fontSize: 13, margin: 0 }}>
                      표 데이터를 불러오는 중 오류가 발생했습니다.
                    </p>
                  )}
                  {!isTablesLoading && !isTablesError && !tablesResult?.tables.length && (
                    <p style={{ color: 'var(--color-text-muted)', fontSize: 13, margin: 0 }}>
                      추출된 표가 없습니다.
                    </p>
                  )}
                  {!isTablesLoading && !!tablesResult?.tables.length && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-5)' }}>
                      {tablesResult.tables.map((table, i) => (
                        <div key={i}>
                          <div style={{ fontSize: 12, color: 'var(--color-text-muted)', marginBottom: 'var(--space-2)' }}>
                            표 {i + 1}{isPdfDoc ? ` · ${table.page_number}쪽` : ''}
                          </div>
                          <div style={{ overflowX: 'auto', border: '1px solid #e2e8f0', borderRadius: 'var(--radius-sm)' }}>
                            <table style={{ borderCollapse: 'collapse', fontSize: 13, whiteSpace: 'nowrap' }}>
                              <tbody>
                                {table.rows.map((row, ri) => (
                                  <tr key={ri}>
                                    {row.map((cell, ci) => (
                                      <td
                                        key={ci}
                                        style={{
                                          padding: '6px 10px',
                                          border: '1px solid #e2e8f0',
                                          background: ri === 0 ? '#f8fafc' : undefined,
                                          fontWeight: ri === 0 ? 600 : 400,
                                        }}
                                      >
                                        {cell}
                                      </td>
                                    ))}
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </>
              )}

              {activeTab === 'images' && (
                <>
                  {isImagesLoading && (
                    <div style={{ display: 'flex', justifyContent: 'center', padding: 'var(--space-6)' }}>
                      <Loader2 size={20} style={{ animation: 'spin 1s linear infinite', color: 'var(--color-text-muted)' }} />
                    </div>
                  )}
                  {!isImagesLoading && isImagesError && (
                    <p style={{ color: '#dc2626', fontSize: 13, margin: 0 }}>
                      그림 데이터를 불러오는 중 오류가 발생했습니다.
                    </p>
                  )}
                  {!isImagesLoading && !isImagesError && !imagesResult?.images.length && (
                    <p style={{ color: 'var(--color-text-muted)', fontSize: 13, margin: 0 }}>
                      추출된 그림이 없습니다.
                    </p>
                  )}
                  {!isImagesLoading && !!imagesResult?.images.length && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-6)' }}>
                      {imagesResult.images.map((img, i) => (
                        <div key={i}>
                          <div style={{ fontSize: 12, color: 'var(--color-text-muted)', marginBottom: 'var(--space-2)' }}>
                            그림 {i + 1}{isPdfDoc ? ` · ${img.page_number}쪽` : ''}
                          </div>
                          <div style={{
                            border: '1px solid #e2e8f0', borderRadius: 'var(--radius-sm)',
                            padding: 'var(--space-3)', background: '#f8fafc',
                            display: 'flex', justifyContent: 'center',
                          }}>
                            <img
                              src={img.url}
                              alt={`그림 ${i + 1}`}
                              loading="lazy"
                              style={{ maxWidth: '100%', maxHeight: 360, objectFit: 'contain' }}
                            />
                          </div>
                          {img.text && (
                            <p style={{
                              fontSize: 12, color: 'var(--color-text-muted)', lineHeight: 1.6,
                              whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                              margin: 'var(--space-2) 0 0',
                            }}>
                              {img.text}
                            </p>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </>
              )}
              {activeTab === 'chunks' && (
                <>
                  {isChunksLoading && (
                    <div style={{ display: 'flex', justifyContent: 'center', padding: 'var(--space-6)' }}>
                      <Loader2 size={20} style={{ animation: 'spin 1s linear infinite', color: 'var(--color-text-muted)' }} />
                    </div>
                  )}
                  {!isChunksLoading && isChunksError && (
                    <p style={{ color: '#dc2626', fontSize: 13, margin: 0 }}>
                      청크를 불러오는 중 오류가 발생했습니다.
                    </p>
                  )}
                  {!isChunksLoading && !isChunksError && !chunksResult?.chunks.length && (
                    <p style={{ color: 'var(--color-text-muted)', fontSize: 13, margin: 0 }}>
                      저장된 청크가 없습니다.
                    </p>
                  )}
                  {!isChunksLoading && !!chunksResult?.chunks.length && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
                      <p style={{ fontSize: 12, color: 'var(--color-text-muted)', margin: 0 }}>
                        총 {chunksResult.chunks.length}개 청크. 텍스트를 수정하면 해당 청크만 다시 임베딩되고,
                        "검색 제외"된 청크는 검색·채팅에서 사용되지 않습니다.
                      </p>
                      {chunksResult.chunks.map((chunk) => (
                        <div
                          key={chunk.id}
                          style={{
                            border: '1px solid #e2e8f0', borderRadius: 'var(--radius-md)',
                            padding: 'var(--space-3)', background: '#fff',
                            opacity: chunk.disabled ? 0.55 : 1,
                          }}
                        >
                          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 'var(--space-2)' }}>
                            <span style={{ fontSize: 12, fontWeight: 600 }}>
                              청크 #{chunk.chunk_index + 1}
                              {isPdfDoc && chunk.page_number ? ` · ${chunk.page_number}쪽` : ''}
                            </span>
                            {chunk.edited && <span className="krds-badge small bg-information">수정됨</span>}
                            {chunk.disabled && <span className="krds-badge small bg-gray">검색 제외</span>}
                            <span
                              title="검색/채팅 응답에서 이 청크가 실제로 반환된 횟수"
                              style={{
                                fontSize: 11,
                                color: chunk.hit_count > 0 ? 'var(--color-text-muted)' : '#b45309',
                              }}
                            >
                              조회 {chunk.hit_count}회{chunk.hit_count === 0 ? ' · 미조회' : ''}
                            </span>
                            <span style={{ flex: 1 }} />
                            {chunkEditId !== chunk.id && (
                              <>
                                <button
                                  onClick={() => { setChunkEditId(chunk.id); setChunkEditText(chunk.text) }}
                                  className="krds-btn text small"
                                  style={{ cursor: 'pointer' }}
                                >
                                  수정
                                </button>
                                <button
                                  onClick={() => updateChunk.mutate({ docId: id, chunkId: chunk.id, disabled: !chunk.disabled })}
                                  disabled={updateChunk.isPending}
                                  className="krds-btn text small"
                                  style={{ cursor: 'pointer' }}
                                >
                                  {chunk.disabled ? '검색 포함' : '검색 제외'}
                                </button>
                                <button
                                  onClick={() => {
                                    if (window.confirm(`청크 #${chunk.chunk_index + 1}을(를) 삭제하시겠습니까? 벡터DB에서 제거되며 되돌릴 수 없습니다.`)) {
                                      deleteChunk.mutate({ docId: id, chunkId: chunk.id })
                                    }
                                  }}
                                  disabled={deleteChunk.isPending}
                                  className="krds-btn text small"
                                  style={{ cursor: 'pointer', color: '#dc2626' }}
                                >
                                  삭제
                                </button>
                              </>
                            )}
                          </div>
                          {chunkEditId === chunk.id ? (
                            <div>
                              <textarea
                                className="krds-input"
                                value={chunkEditText}
                                onChange={(e) => setChunkEditText(e.target.value)}
                                rows={8}
                                style={{ width: '100%', boxSizing: 'border-box', fontSize: 12, lineHeight: 1.6, fontFamily: 'inherit', resize: 'vertical' }}
                              />
                              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 8 }}>
                                <button
                                  onClick={() => setChunkEditId(null)}
                                  disabled={updateChunk.isPending}
                                  className="krds-btn secondary small"
                                  style={{ cursor: 'pointer' }}
                                >
                                  취소
                                </button>
                                <button
                                  onClick={() =>
                                    updateChunk.mutate(
                                      { docId: id, chunkId: chunk.id, text: chunkEditText },
                                      { onSuccess: () => setChunkEditId(null) }
                                    )
                                  }
                                  disabled={updateChunk.isPending || !chunkEditText.trim()}
                                  className="krds-btn primary small"
                                  style={{ display: 'inline-flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}
                                >
                                  {updateChunk.isPending && <Loader2 size={12} style={{ animation: 'spin 1s linear infinite' }} />}
                                  저장 (재임베딩)
                                </button>
                              </div>
                            </div>
                          ) : (
                            <pre style={{
                              fontSize: 12, lineHeight: 1.6, whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                              fontFamily: 'inherit', margin: 0, color: '#334155',
                            }}>
                              {chunk.text}
                            </pre>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </>
              )}
              {activeTab === 'original' && (() => {
                const pages = pagesTextResult?.pages ?? []
                const isPdfPreview = previewResult?.kind === 'pdf'
                const maxPage = isPdfPreview && pages.length
                  ? Math.max(...pages.map((p) => p.page_number))
                  : 1
                const clampedPage = Math.min(Math.max(originalPage, 1), maxPage)
                const currentPageText = isPdfPreview
                  ? pages.filter((p) => p.page_number === clampedPage).map((p) => p.text).join('\n\n')
                  : null
                return (
                  <div style={{ display: 'flex', flexDirection: 'column', height: '100%', gap: 'var(--space-2)' }}>
                    {isPdfPreview && maxPage > 1 && (
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
                        <button
                          className="krds-btn secondary small"
                          disabled={clampedPage <= 1}
                          onClick={() => setOriginalPage(clampedPage - 1)}
                          style={{ cursor: 'pointer' }}
                        >
                          ◀ 이전
                        </button>
                        <span style={{ fontSize: 13 }}>
                          {clampedPage} / {maxPage} 쪽
                        </span>
                        <button
                          className="krds-btn secondary small"
                          disabled={clampedPage >= maxPage}
                          onClick={() => setOriginalPage(clampedPage + 1)}
                          style={{ cursor: 'pointer' }}
                        >
                          다음 ▶
                        </button>
                        <span style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
                          원본과 파싱 텍스트가 같은 쪽으로 함께 이동합니다
                        </span>
                      </div>
                    )}
                    {previewResult?.approximate && (
                      <p style={{ fontSize: 12, color: '#b45309', margin: 0, flexShrink: 0 }}>
                        이 형식은 원본을 직접 렌더링할 수 없어 재구성한 근사치입니다 — 레이아웃·글꼴·이미지 배치가 실제 원본과 다를 수 있습니다. 정확한 원본은 "원본 다운로드"를 이용하세요.
                      </p>
                    )}
                    <div style={{ flex: 1, minHeight: 0, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 'var(--space-4)' }}>
                      <div style={{ minHeight: 0, display: 'flex', flexDirection: 'column' }}>
                        <p style={{ fontSize: 12, color: 'var(--color-text-muted)', margin: '0 0 var(--space-2)', flexShrink: 0 }}>
                          {isPdfPreview ? '원본 PDF' : '원본 (변환 미리보기)'}
                        </p>
                        {isPreviewError && (
                          <p style={{ color: '#dc2626', fontSize: 13 }}>원문 미리보기를 생성하지 못했습니다.</p>
                        )}
                        {!isPreviewError && previewResult?.url ? (
                          <iframe
                            key={isPdfPreview ? clampedPage : 'html'}
                            src={isPdfPreview ? `${previewResult.url}#page=${clampedPage}` : previewResult.url}
                            title="원본 문서"
                            style={{ flex: 1, width: '100%', border: '1px solid #e2e8f0', borderRadius: 'var(--radius-sm)', background: '#fff' }}
                          />
                        ) : !isPreviewError && (
                          <div style={{ display: 'flex', justifyContent: 'center', padding: 'var(--space-6)' }}>
                            <Loader2 size={20} style={{ animation: 'spin 1s linear infinite', color: 'var(--color-text-muted)' }} />
                          </div>
                        )}
                      </div>
                      <div style={{ minHeight: 0, display: 'flex', flexDirection: 'column' }}>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexShrink: 0 }}>
                          <p style={{ fontSize: 12, color: 'var(--color-text-muted)', margin: '0 0 var(--space-2)' }}>
                            파싱된 텍스트{isPdfPreview && maxPage > 1 ? ` (${clampedPage}쪽)` : ''}
                          </p>
                          <ViewModeToggle showJson={showJson} onChange={setShowJson} />
                        </div>
                        <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', border: '1px solid #e2e8f0', borderRadius: 'var(--radius-sm)', padding: 'var(--space-3)', background: showJson ? '#f8fafc' : '#fff' }}>
                          {isContentLoading && (
                            <div style={{ display: 'flex', justifyContent: 'center', padding: 'var(--space-6)' }}>
                              <Loader2 size={20} style={{ animation: 'spin 1s linear infinite', color: 'var(--color-text-muted)' }} />
                            </div>
                          )}
                          {!isContentLoading && (
                            <pre style={{
                              fontSize: showJson ? 12 : 12, lineHeight: showJson ? 1.6 : 1.7,
                              whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                              fontFamily: showJson ? 'monospace' : 'inherit', margin: 0,
                            }}>
                              {(() => {
                                const pageText = currentPageText ?? content?.full_text ?? ''
                                return showJson ? toBlocksJson(pageText) : pageText
                              })()}
                            </pre>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                )
              })()}
            </div>

            {activeTab === 'edit' && !isContentLoading && content && content.chunk_count > 0 && (
              <div style={{
                flexShrink: 0, borderTop: '1px solid #e2e8f0',
                padding: 'var(--space-3) var(--space-5)',
                display: 'flex', justifyContent: 'flex-end', gap: 'var(--space-2)',
              }}>
                <button
                  onClick={() => setEditedContent(editBaseline ?? '')}
                  disabled={reprocess.isPending}
                  className="krds-btn secondary medium"
                  style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', cursor: 'pointer' }}
                >
                  <X size={14} /> 되돌리기
                </button>
                <button
                  onClick={() =>
                    reprocess.mutate(
                      { id, editedText: editedContent },
                      { onSuccess: () => { setEditBaseline(null); setActiveTab('summary') } }
                    )
                  }
                  disabled={reprocess.isPending}
                  className="krds-btn primary medium"
                  style={{
                    display: 'flex', alignItems: 'center', gap: 'var(--space-2)',
                    cursor: reprocess.isPending ? 'not-allowed' : 'pointer',
                    opacity: reprocess.isPending ? 0.7 : 1,
                  }}
                >
                  {reprocess.isPending
                    ? <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} />
                    : <Save size={14} />}
                  저장 후 재처리
                </button>
              </div>
            )}
          </div>
        </div>
      )}
      </div>
    </div>
  )
}
