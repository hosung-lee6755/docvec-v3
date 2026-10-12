import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { AlertTriangle, ArrowLeft, Download, Loader2, Save, X } from 'lucide-react'
import { useAcceptTagSuggestion, useDeleteChunk, useDismissTagSuggestion, useDocument, useDocumentChunks, useDocumentContent, useDocumentImages, useDocumentPagesText, useDocumentPreview, useDocumentRevisions, useDocumentTables, useDownloadDocument, useProceedDocument, useReprocessDocument, useRestoreRevision, useRetryDocument, useUpdateChunk, useUpdateDocumentTags } from '../hooks/useDocuments'
import { useDocumentQuality, useDocumentRuns } from '../hooks/useDocumentRuns'
import { useCancelRun, useResumeRun, useWorkflowRun } from '../hooks/useWorkflows'
import StepTimeline from '../components/workflow/StepTimeline'
import ReprocessModal from '../components/ReprocessModal'
import StructureTab from '../components/document-detail/StructureTab'
import ElementsTab from '../components/document-detail/ElementsTab'
import CleaningChangesTab from '../components/document-detail/CleaningChangesTab'
import DictionaryApplicationsTab from '../components/document-detail/DictionaryApplicationsTab'
import PiiDetectionsTab from '../components/document-detail/PiiDetectionsTab'
import { useUpdateDocumentMetadata } from '../hooks/useDocumentMetadata'
import MutationErrorBanner from '../components/document-detail/MutationErrorBanner'
import { useDocumentNodes } from '../hooks/useDocumentStructure'
import EditTab from '../components/document-detail/EditTab'
import TablesTab from '../components/document-detail/TablesTab'
import ImagesTab from '../components/document-detail/ImagesTab'
import ChunksTab from '../components/document-detail/ChunksTab'
import OriginalTab from '../components/document-detail/OriginalTab'
import QualityTab from '../components/document-detail/QualityTab'
import HistoryTab from '../components/document-detail/HistoryTab'
import DocumentSidebar from '../components/document-detail/DocumentSidebar'
import { ViewModeToggle } from '../components/document-detail/documentDetailParts'
import { toBlocksJson, type TabKey } from '../components/document-detail/documentDetailHelpers'

// 문서 요약(doc.summary)·추천 태그는 분석 워크플로우 산출물이라 탭이 아니라
// 왼쪽 메타데이터 패널로 이동했다 — 나머지는 전부 전처리 워크플로우 산출물이다.
const TABS: { key: TabKey; label: string; pdfOnly?: boolean }[] = [
  { key: 'original', label: '원문 대조' },
  { key: 'structure', label: '구조' },
  { key: 'elements', label: '요소', pdfOnly: true },
  { key: 'cleaning', label: '정제 비교' },
  { key: 'dictionary', label: '사전 적용' },
  { key: 'pii', label: '민감정보' },
  { key: 'chunks', label: '청크' },
  { key: 'tables', label: '표' },
  { key: 'images', label: '그림' },
  { key: 'edit', label: 'RAG 데이터 수정' },
  { key: 'quality', label: '품질' },
  { key: 'history', label: '처리 이력' },
]

const PROCESSING_STATUSES = new Set([
  'QUEUED', 'INGESTING', 'PARSING', 'STRUCTURING',
  'NORMALIZING', 'CHUNKING', 'EMBEDDING', 'UPLOADING',
  'VALIDATING', 'MASKING',
])

export default function DocumentDetailPage() {
  const { id = '', projectId } = useParams<{ id: string; projectId?: string }>()
  const navigate = useNavigate()
  const backTo = projectId ? `/projects/${projectId}/documents` : '/documents'
  const { data: doc, isLoading, isError } = useDocument(id)
  const [activeTab, setActiveTab] = useState<TabKey>('original')
  // 품질 탭의 "너무 짧은/큰 청크" 경고를 클릭했을 때 청크 탭으로 이동만 하는 게
  // 아니라 실제 문제 청크로 스크롤하기 위한 목표 id 목록.
  const [highlightChunkIds, setHighlightChunkIds] = useState<string[] | null>(null)
  const needsContent = activeTab === 'edit' || activeTab === 'original'
  const { data: content, isLoading: isContentLoading, isError: isContentError } = useDocumentContent(id, needsContent)
  const { data: tablesResult, isLoading: isTablesLoading, isError: isTablesError } = useDocumentTables(id, activeTab === 'tables')
  const { data: imagesResult, isLoading: isImagesLoading, isError: isImagesError } = useDocumentImages(id, activeTab === 'images')
  // 청크 탭을 열지 않아도 왼쪽 RAG 현황 패널이 청크 개수를 보여줘야 하므로
  // INDEXED 상태가 되면 곧바로 가져온다(탭 진입 시점까지 미루지 않음). WAITING_REVIEW도
  // 포함 — 검토 게이트에 걸린 문서도 chunk_split이 이미 만든(아직 미임베딩) 청크를
  // 패널에서 바로 보여줘야 한다.
  const { data: chunksResult, isLoading: isChunksLoading, isError: isChunksError } = useDocumentChunks(id, activeTab === 'chunks' || doc?.status === 'INDEXED' || doc?.status === 'WAITING_REVIEW')
  const { data: previewResult, isError: isPreviewError } = useDocumentPreview(id, activeTab === 'original')
  const { data: pagesTextResult } = useDocumentPagesText(id, activeTab === 'original')
  const [originalPage, setOriginalPage] = useState(1)
  const { data: revisionsResult } = useDocumentRevisions(id, activeTab === 'edit')
  const { data: editNodesResult } = useDocumentNodes(id, activeTab === 'edit')
  const download = useDownloadDocument()
  const proceed = useProceedDocument()
  const reprocess = useReprocessDocument()
  const updateChunk = useUpdateChunk()
  const deleteChunk = useDeleteChunk()
  const restoreRevision = useRestoreRevision()
  const retryDoc = useRetryDocument()
  const updateTags = useUpdateDocumentTags()
  const updateMetadata = useUpdateDocumentMetadata()
  const acceptSuggestion = useAcceptTagSuggestion()
  const dismissSuggestion = useDismissTagSuggestion()
  const [chunkEditId, setChunkEditId] = useState<string | null>(null)
  // Chunk 계층형 Parent Retrieval(메타 정보 생성.txt 3절, Phase 9) — "상위
  // 청크 보기" 토글로 펼쳐 보여줄 청크 id(한 번에 하나만).
  const [expandedParentChunkId, setExpandedParentChunkId] = useState<string | null>(null)
  const [chunkEditText, setChunkEditText] = useState('')
  const [tagInput, setTagInput] = useState('')
  const [reviewTextOverride, setReviewTextOverride] = useState<string | null>(null)
  const reviewText = reviewTextOverride ?? doc?.parsed_text ?? ''
  const [editedContent, setEditedContent] = useState('')
  const [editBaseline, setEditBaseline] = useState<string | null>(null)
  const [showJson, setShowJson] = useState(false)
  const isPdfDoc = doc?.original_filename?.toLowerCase().endsWith('.pdf') ?? false

  // Reset per-document state when document ID changes
  useEffect(() => {
    setActiveTab('original')
    setEditedContent('')
    setEditBaseline(null)
    setReviewTextOverride(null)
    setSelectedRunId(null)
    setHighlightChunkIds([])
    setShowJson(false)
    setTagInput('')
  }, [id])

  useEffect(() => {
    if (activeTab === 'edit' && content && editBaseline === null) {
      setEditedContent(content.full_text)
      setEditBaseline(content.full_text)
    }
  }, [activeTab, content, editBaseline])

  // 품질 경고 클릭으로 청크 탭에 들어왔을 때 실제 문제 청크로 스크롤한다 — 청크
  // 탭으로만 이동시키면 결국 사용자가 목록을 훑어 찾아야 하는 문제가 그대로다.
  // 스크롤 후 highlightChunkIds를 비워서 같은 청크를 반복으로 스크롤하지 않도록 한다.
  useEffect(() => {
    if (activeTab !== 'chunks' || !highlightChunkIds?.length || !chunksResult) return
    const targetId = highlightChunkIds.find((cid) => chunksResult.chunks.some((c) => c.id === cid))
    if (!targetId) return
    const el = document.getElementById(`chunk-row-${targetId}`)
    el?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    // Clear after scroll to prevent re-firing on chunk refetch
    setHighlightChunkIds([])
  }, [activeTab, highlightChunkIds, chunksResult])

  useEffect(() => {
    if (doc?.status === 'WAITING_REVIEW' && activeTab === 'original') {
      setActiveTab('quality')
    }
  }, [doc?.status, activeTab])

  const isProcessing = doc && PROCESSING_STATUSES.has(doc.status)
  // "전처리 단계" 패널의 데이터 소스 — ProcessingJob은 13개 블록 중 text_extract만
  // 기록해 그 외 블록 진행이 전혀 안 보였다. DAG 실행기가 남기는 WorkflowRun의 실제
  // 스텝별 진행 상황으로 대체한다.
  const { data: activeRunPanel } = useWorkflowRun(doc?.active_run_id ?? null)
  const isIndexed = doc?.status === 'INDEXED'
  const isAnalyzing = doc?.status === 'ANALYZING'
  // ANALYZING은 전처리가 이미 끝나고 분석 워크플로우만 뒤에서 도는 상태라
  // RAG 현황/탭/다운로드 등은 INDEXED와 동일하게 취급한다 — isIndexed 하나로는
  // 이 상태가 새로 생기면서 해당 UI가 전부 숨어버렸다.
  const isReady = isIndexed || isAnalyzing
  const isWaitingReview = doc?.status === 'WAITING_REVIEW'
  const showWorkflowTabs = isReady || isWaitingReview

  const { data: runsData } = useDocumentRuns(id, showWorkflowTabs)
  const latestRun = runsData?.runs[0] ?? null
  const { data: qualityReport } = useDocumentQuality(id, showWorkflowTabs)
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)
  const historyRunId = selectedRunId ?? latestRun?.id ?? null
  const { data: historyRunDetail } = useWorkflowRun(activeTab === 'history' ? historyRunId : null)
  const resumeRun = useResumeRun()
  const cancelRun = useCancelRun()
  const [reprocessModal, setReprocessModal] = useState<{ blockInstanceId: string | null } | null>(null)

  const handleDownload = () => {
    download.mutate(id, {
      onSuccess: (url) => {
        const a = document.createElement('a')
        a.href = url
        a.rel = 'noopener noreferrer'
        a.click()
      },
      onError: () => {
        // Error message will be shown by mutation error handler
      },
    })
  }

  if (isLoading) {
    return (
      <div style={{ padding: 'var(--space-8)', color: 'var(--color-text-muted)' }}>
        로딩 중...
      </div>
    )
  }

  if (!doc) {
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
      `}</style>
      <button onClick={() => navigate(backTo)} className="krds-btn text small" style={{ marginBottom: 'var(--space-4)', display: 'inline-flex', alignItems: 'center', gap: 6, background: 'none', border: 'none', cursor: 'pointer', color: 'var(--color-text-muted)', fontSize: 14, padding: 0 }}>
        <ArrowLeft size={16} /> 문서 목록
      </button>

      {isError && (
        <div role="alert" style={{ marginBottom: 'var(--space-4)', padding: 'var(--space-3) var(--space-4)', background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 'var(--radius-md)', display: 'flex', alignItems: 'flex-start', gap: 'var(--space-3)' }}>
          <AlertTriangle size={18} style={{ color: '#dc2626', flexShrink: 0 }} />
          <div style={{ flex: 1 }}>
            <p style={{ fontSize: 13, color: '#dc2626', margin: '0 0 var(--space-2)', fontWeight: 600 }}>문서 정보를 새로고침하는 중 오류가 발생했습니다</p>
            <p style={{ fontSize: 12, color: '#991b1b', margin: 0 }}>표시된 정보가 최신이 아닐 수 있습니다. 페이지를 새로고침하거나 나중에 다시 시도하세요.</p>
          </div>
        </div>
      )}

      <MutationErrorBanner
        failures={[
          { label: '메타데이터 저장', mutation: updateMetadata },
          { label: '태그 저장', mutation: updateTags },
          { label: '추천 태그 추가', mutation: acceptSuggestion },
          { label: '추천 태그 삭제', mutation: dismissSuggestion },
          { label: '버전 복원', mutation: restoreRevision },
          { label: '청크 수정', mutation: updateChunk },
          { label: '청크 삭제', mutation: deleteChunk },
          { label: '재시도 요청', mutation: retryDoc },
        ]
          .filter(({ mutation }) => mutation.isError)
          .map(({ label, mutation }) => ({ label, onDismiss: () => mutation.reset() }))}
      />

      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', marginBottom: 'var(--space-6)' }}>
        <h1 style={{ fontSize: 24, fontWeight: 700, wordBreak: 'break-all', margin: 0 }}>
          {doc.original_filename}
        </h1>
        {isReady && (
          <button
            onClick={handleDownload}
            disabled={download.isPending}
            title="원본 다운로드"
            aria-label="원본 다운로드"
            className="krds-btn text xsmall icon-btn accent"
          >
            {download.isPending
              ? <Loader2 size={16} style={{ animation: 'spin 1s linear infinite' }} />
              : <Download size={16} />}
          </button>
        )}
        {isReady && (
          <button
            onClick={() => setReprocessModal({ blockInstanceId: null })}
            className="krds-btn secondary small"
            style={{ cursor: 'pointer' }}
          >
            재처리
          </button>
        )}
      </div>

      {isWaitingReview && (
        <div style={{
          display: 'flex', alignItems: 'flex-start', gap: 'var(--space-3)',
          padding: 'var(--space-3) var(--space-4)', marginBottom: 'var(--space-6)',
          background: '#fffbeb', border: '1px solid #fde68a', borderRadius: 'var(--radius-md)',
        }}>
          <AlertTriangle size={18} style={{ color: '#b45309', flexShrink: 0, marginTop: 2 }} />
          <div style={{ flex: 1 }}>
            <p style={{ fontSize: 13, fontWeight: 600, color: '#92400e', margin: 0 }}>
              이 문서는 검토 대기 중입니다
            </p>
            <p style={{ fontSize: 12, color: '#92400e', margin: '2px 0 var(--space-2)' }}>
              {qualityReport && !qualityReport.warnings?.length
                ? '이 워크플로우의 검토 정책상 모든 문서가 검토 대상입니다(발견된 품질 경고는 없습니다). 품질 탭에서 점수 근거를 확인하고 승인 또는 반려하세요.'
                : '품질 검사에서 경고가 발견되어 자동 진행이 중단되었습니다. 품질 탭에서 결과를 확인하고 승인 또는 반려하세요.'}
            </p>
            <div style={{ display: 'flex', gap: 'var(--space-2)' }}>
              <button
                onClick={() => setActiveTab('quality')}
                className="krds-btn primary small"
                style={{ cursor: 'pointer' }}
              >
                품질 탭으로 이동
              </button>
            </div>
          </div>
        </div>
      )}

      {reprocessModal && (
        <ReprocessModal
          documentId={id}
          initialBlockInstanceId={reprocessModal.blockInstanceId}
          onClose={() => setReprocessModal(null)}
          onStarted={() => setActiveTab('history')}
        />
      )}

      <div style={{
        display: 'grid',
        gridTemplateColumns: isReady ? 'minmax(280px, 360px) 1fr' : '1fr',
        gap: 'var(--space-8)',
        alignItems: 'start',
      }}>
      <div>
        <DocumentSidebar
          doc={doc}
          isReady={isReady}
          isProcessing={!!isProcessing}
          isAnalyzing={isAnalyzing}
          chunksResult={chunksResult}
          qualityReport={qualityReport}
          latestRun={latestRun}
          updateMetadata={updateMetadata}
          updateTags={updateTags}
          acceptSuggestion={acceptSuggestion}
          dismissSuggestion={dismissSuggestion}
          tagInput={tagInput}
          onTagInputChange={setTagInput}
          onActiveTabChange={setActiveTab}
        />

      {isProcessing && !!activeRunPanel?.steps.length && (
        <div style={{ marginTop: 'var(--space-6)', maxWidth: 640 }}>
          <h2 style={{ fontSize: 14, fontWeight: 600, marginBottom: 'var(--space-3)' }}>
            전처리 단계
          </h2>
          <StepTimeline steps={activeRunPanel.steps} />
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
          <div style={{ marginTop: 'var(--space-3)', display: 'flex', justifyContent: 'flex-end', gap: 'var(--space-2)' }}>
            <button
              onClick={() => setReprocessModal({ blockInstanceId: null })}
              className="krds-btn secondary small"
              style={{ cursor: 'pointer' }}
              title="시간 제한 등 설정을 조정한 뒤, 멈췄던 블록부터 다시 시작합니다"
            >
              재처리 (설정 조정)
            </button>
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

      {showWorkflowTabs && (
        <div>
          <div style={{ display: 'flex', gap: 'var(--space-1)', borderBottom: '1px solid var(--color-border)', marginBottom: 'var(--space-4)' }}>
            {TABS.filter((t) => {
              const workflowTabKeys: TabKey[] = ['quality', 'history', 'structure', 'cleaning', 'dictionary', 'pii', 'chunks']
              if (workflowTabKeys.includes(t.key)) return true
              return isReady && (!t.pdfOnly || isPdfDoc)
            }).map((t) => (
              <button
                key={t.key}
                role="tab"
                aria-selected={activeTab === t.key}
                aria-controls={`tabpanel-${t.key}`}
                onClick={() => setActiveTab(t.key)}
                type="button"
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
            display: 'flex', flexDirection: 'column', height: 'calc(100vh - 220px)', minHeight: 720,
            background: '#fff', border: '1px solid #e2e8f0',
            borderRadius: 'var(--radius-md)', overflow: 'hidden',
          }}>
            <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: 'var(--space-5)' }}>
              {activeTab === 'edit' && (
                <EditTab
                  documentId={id}
                  doc={doc}
                  isLoading={isContentLoading}
                  content={content}
                  isContentError={isContentError}
                  revisionsResult={revisionsResult}
                  editNodesResult={editNodesResult}
                  editedContent={editedContent}
                  showJson={showJson}
                  reprocess={reprocess}
                  restoreRevision={restoreRevision}
                  onEditedContentChange={setEditedContent}
                  onShowJsonChange={setShowJson}
                  onActivateTab={setActiveTab}
                />
              )}

              {activeTab === 'tables' && (
                <TablesTab
                  isLoading={isTablesLoading}
                  isError={isTablesError}
                  tablesResult={tablesResult}
                  isPdfDoc={isPdfDoc}
                />
              )}

              {activeTab === 'images' && (
                <ImagesTab
                  isLoading={isImagesLoading}
                  isError={isImagesError}
                  imagesResult={imagesResult}
                  isPdfDoc={isPdfDoc}
                />
              )}
              {activeTab === 'chunks' && (
                <ChunksTab
                  documentId={id}
                  isLoading={isChunksLoading}
                  isError={isChunksError}
                  chunksResult={chunksResult}
                  isPdfDoc={isPdfDoc}
                  chunkEditId={chunkEditId}
                  chunkEditText={chunkEditText}
                  expandedParentChunkId={expandedParentChunkId}
                  highlightChunkIds={highlightChunkIds}
                  updateChunk={updateChunk}
                  deleteChunk={deleteChunk}
                  onChunkEditIdChange={setChunkEditId}
                  onChunkEditTextChange={setChunkEditText}
                  onExpandedParentChunkIdChange={setExpandedParentChunkId}
                  onOriginalPageChange={setOriginalPage}
                  onActivateTab={setActiveTab}
                />
              )}
              {activeTab === 'original' && (
                <OriginalTab
                  isContentLoading={isContentLoading}
                  isPreviewError={isPreviewError}
                  content={content}
                  pagesTextResult={pagesTextResult}
                  previewResult={previewResult}
                  isPdfDoc={isPdfDoc}
                  originalPage={originalPage}
                  showJson={showJson}
                  onOriginalPageChange={setOriginalPage}
                  onShowJsonChange={setShowJson}
                />
              )}

              {activeTab === 'structure' && (
                <StructureTab
                  documentId={id}
                  onViewInOriginal={(pageNumber) => { setOriginalPage(pageNumber); setActiveTab('original') }}
                  onReprocessFromStructure={(blockInstanceId) => setReprocessModal({ blockInstanceId })}
                />
              )}
              {activeTab === 'elements' && <ElementsTab documentId={id} />}
              {activeTab === 'cleaning' && <CleaningChangesTab documentId={id} />}
              {activeTab === 'dictionary' && (
                <DictionaryApplicationsTab
                  documentId={id}
                  onReprocessFromDictionary={() => setReprocessModal({ blockInstanceId: null })}
                />
              )}
              {activeTab === 'pii' && <PiiDetectionsTab documentId={id} />}

              {activeTab === 'quality' && (
                <QualityTab
                  qualityReport={qualityReport}
                  isWaitingReview={isWaitingReview}
                  latestRun={latestRun}
                  cancelRun={cancelRun}
                  resumeRun={resumeRun}
                  onHighlightChunkIdsChange={setHighlightChunkIds}
                  onActivateTab={setActiveTab}
                />
              )}

              {activeTab === 'history' && (
                <HistoryTab
                  runsData={runsData}
                  selectedRunId={historyRunId}
                  historyRunDetail={historyRunDetail}
                  onSelectedRunIdChange={setSelectedRunId}
                  onReprocessFromHistory={(blockInstanceId) => setReprocessModal({ blockInstanceId })}
                />
              )}
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
                      { onSuccess: () => { setEditBaseline(null); setActiveTab('original') } }
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
