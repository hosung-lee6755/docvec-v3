import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Download, Loader2, Save, X } from 'lucide-react'
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
import { useUpdateDocumentMetadata, type SecurityLevel } from '../hooks/useDocumentMetadata'
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
import OcrConfidencePanel from '../components/document-detail/OcrConfidencePanel'
import VersionHistoryPanel from '../components/document-detail/VersionHistoryPanel'
import { SECURITY_LEVEL_LABELS } from '../hooks/useAccess'
import {
  Alert, Button, IconButton, Page, PageHeader, SecurityLevelBadge, Split, StatusBadge, Tabs, Textarea,
} from '../components/ui'

// 문서 요약(doc.summary)·추천 태그는 분석 워크플로우 산출물이라 탭이 아니라
// 옆 정보 패널로 이동했다 — 나머지는 전부 전처리 워크플로우 산출물이다.
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

const WORKFLOW_TAB_KEYS: TabKey[] = ['quality', 'history', 'structure', 'cleaning', 'dictionary', 'pii', 'chunks']

const PROCESSING_STATUSES = new Set([
  'QUEUED', 'INGESTING', 'PARSING', 'STRUCTURING',
  'NORMALIZING', 'CHUNKING', 'EMBEDDING', 'UPLOADING',
  'VALIDATING', 'MASKING',
])

const TAB_ID_PREFIX = 'doc-detail'

export default function DocumentDetailPage() {
  const { id = '', projectId } = useParams<{ id: string; projectId?: string }>()
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
      <Page>
        <p style={{ padding: 'var(--space-8)', color: 'var(--color-text-muted)' }}>
          로딩 중...
        </p>
      </Page>
    )
  }

  if (!doc) {
    return (
      <Page>
        <PageHeader breadcrumb={<Link to={backTo}>문서 목록</Link>} title="문서 상세" />
        <Alert tone="danger">문서를 불러올 수 없습니다.</Alert>
      </Page>
    )
  }

  const visibleTabs = TABS.filter((t) => {
    if (WORKFLOW_TAB_KEYS.includes(t.key)) return true
    return isReady && (!t.pdfOnly || isPdfDoc)
  })
  const securityLabel = doc.security_level
    ? SECURITY_LEVEL_LABELS[doc.security_level as SecurityLevel] ?? doc.security_level
    : null

  return (
    <Page>

      <PageHeader
        breadcrumb={<Link to={backTo}>문서 목록</Link>}
        title={doc.original_filename}
        subtitle={(
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 'var(--space-2)' }}>
            <StatusBadge status={doc.status} />
            {doc.security_level && securityLabel && (
              <SecurityLevelBadge level={doc.security_level} label={securityLabel} />
            )}
          </span>
        )}
        actions={(
          <>
            {isReady && (
              <IconButton
                label="원본 다운로드"
                onClick={handleDownload}
                disabled={download.isPending}
              >
                {download.isPending
                  ? <Loader2 size={16} style={{ animation: 'spin 1s linear infinite' }} />
                  : <Download size={16} />}
              </IconButton>
            )}
            {isReady && (
              <Button variant="secondary" size="sm" onClick={() => setReprocessModal({ blockInstanceId: null })}>
                재처리
              </Button>
            )}
          </>
        )}
      />

      {isError && (
        <Alert tone="warning">
          <strong>문서 정보를 새로고침하는 중 오류가 발생했습니다</strong>
          <div>표시된 정보가 최신이 아닐 수 있습니다. 페이지를 새로고침하거나 나중에 다시 시도하세요.</div>
        </Alert>
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

      {reprocessModal && (
        <ReprocessModal
          documentId={id}
          initialBlockInstanceId={reprocessModal.blockInstanceId}
          onClose={() => setReprocessModal(null)}
          onStarted={() => setActiveTab('history')}
        />
      )}

      <Split
        main={(
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-5)', padding: 'var(--space-5)', minWidth: 0 }}>
            {isWaitingReview && (
              <Alert tone="warning">
                <div>
                  <strong>이 문서는 검토 대기 중입니다</strong>
                  <p style={{ margin: '2px 0 var(--space-2)' }}>
                    {qualityReport && !qualityReport.warnings?.length
                      ? '이 워크플로우의 검토 정책상 모든 문서가 검토 대상입니다(발견된 품질 경고는 없습니다). 품질 탭에서 점수 근거를 확인하고 승인 또는 반려하세요.'
                      : '품질 검사에서 경고가 발견되어 자동 진행이 중단되었습니다. 품질 탭에서 결과를 확인하고 승인 또는 반려하세요.'}
                  </p>
                  <Button variant="primary" size="sm" onClick={() => setActiveTab('quality')}>
                    품질 탭으로 이동
                  </Button>
                </div>
              </Alert>
            )}

            {isProcessing && !!activeRunPanel?.steps.length && (
              <section>
                <h2 style={{ fontSize: 'var(--text-sm)', fontWeight: 600, marginBottom: 'var(--space-3)' }}>
                  전처리 단계
                </h2>
                <StepTimeline steps={activeRunPanel.steps} />
              </section>
            )}

            {doc.status === 'REVIEW_PENDING' && (
              <section>
                <h2 style={{ fontSize: 'var(--text-sm)', fontWeight: 600, marginBottom: 'var(--space-2)' }}>
                  파싱 결과 검토
                </h2>
                <p style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-muted)', marginBottom: 'var(--space-3)' }}>
                  텍스트를 확인하고 필요하면 수정한 뒤 다음 단계로 진행하세요. 진행하면 이 텍스트 기준으로 청킹과 임베딩이 실행됩니다.
                </p>
                <ViewModeToggle showJson={showJson} onChange={setShowJson} />
                {showJson ? (
                  <pre style={{
                    width: '100%', boxSizing: 'border-box', fontSize: 'var(--text-xs)', lineHeight: 1.6,
                    fontFamily: 'var(--font-mono)', color: 'var(--color-text)', background: 'var(--color-surface-subtle)',
                    border: '1px solid var(--color-border)', borderRadius: 'var(--radius-sm)',
                    padding: 'var(--space-3)', maxHeight: 400, overflow: 'auto',
                    whiteSpace: 'pre-wrap', wordBreak: 'break-word', marginBottom: 'var(--space-3)',
                  }}>
                    {toBlocksJson(reviewText)}
                  </pre>
                ) : (
                  <Textarea
                    value={reviewText}
                    onChange={(e) => setReviewTextOverride(e.target.value)}
                    rows={16}
                    style={{ marginBottom: 'var(--space-3)', fontSize: 'var(--text-sm)', lineHeight: 1.7, resize: 'vertical' }}
                  />
                )}
                {proceed.isError && (
                  <Alert tone="danger">처리를 재개하지 못했습니다.</Alert>
                )}
                <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 'var(--space-3)' }}>
                  <Button
                    variant="primary"
                    onClick={() => proceed.mutate({ id, editedText: reviewText })}
                    disabled={proceed.isPending}
                    icon={proceed.isPending ? <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} /> : undefined}
                  >
                    다음 단계로 진행
                  </Button>
                </div>
              </section>
            )}

            {doc.status === 'FAILED' && (
              <Alert tone="danger">
                <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)', width: '100%' }}>
                  <h2 style={{ fontSize: 'var(--text-sm)', fontWeight: 600, margin: 0 }}>오류 정보</h2>
                  <pre style={{
                    fontSize: 'var(--text-xs)', fontFamily: 'var(--font-mono)', whiteSpace: 'pre-wrap',
                    wordBreak: 'break-all', margin: 0,
                  }}>
                    {doc.error_message ?? '오류 메시지 없음'}
                  </pre>
                  <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 'var(--space-2)' }}>
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => setReprocessModal({ blockInstanceId: null })}
                      title="시간 제한 등 설정을 조정한 뒤, 멈췄던 블록부터 다시 시작합니다"
                    >
                      재처리 (설정 조정)
                    </Button>
                    <Button
                      variant="primary"
                      size="sm"
                      onClick={() => retryDoc.mutate(id)}
                      disabled={retryDoc.isPending}
                      icon={retryDoc.isPending ? <Loader2 size={13} style={{ animation: 'spin 1s linear infinite' }} /> : undefined}
                    >
                      처리 재시도
                    </Button>
                  </div>
                </div>
              </Alert>
            )}

            {showWorkflowTabs && (
              <div className="ds-card" style={{
                display: 'flex', flexDirection: 'column', height: 'calc(100vh - 260px)', minHeight: 680,
                overflow: 'hidden',
              }}>
                <Tabs
                  items={visibleTabs.map((t) => ({ value: t.key, label: t.label }))}
                  value={activeTab}
                  onChange={setActiveTab}
                  label="문서 상세 탭"
                  idPrefix={TAB_ID_PREFIX}
                />

                <div
                  role="tabpanel"
                  id={`${TAB_ID_PREFIX}-panel-${activeTab}`}
                  aria-labelledby={`${TAB_ID_PREFIX}-tab-${activeTab}`}
                  style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: 'var(--space-5)' }}
                >
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
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-6)' }}>
                      <QualityTab
                        qualityReport={qualityReport}
                        isWaitingReview={isWaitingReview}
                        latestRun={latestRun}
                        cancelRun={cancelRun}
                        resumeRun={resumeRun}
                        onHighlightChunkIdsChange={setHighlightChunkIds}
                        onActivateTab={setActiveTab}
                      />
                      <OcrConfidencePanel documentId={id} />
                    </div>
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
                    flexShrink: 0, borderTop: '1px solid var(--color-border)',
                    padding: 'var(--space-3) var(--space-5)',
                    display: 'flex', justifyContent: 'flex-end', gap: 'var(--space-2)',
                  }}>
                    <Button
                      variant="secondary"
                      onClick={() => setEditedContent(editBaseline ?? '')}
                      disabled={reprocess.isPending}
                      icon={<X size={14} />}
                    >
                      되돌리기
                    </Button>
                    <Button
                      variant="primary"
                      onClick={() =>
                        reprocess.mutate(
                          { id, editedText: editedContent },
                          { onSuccess: () => { setEditBaseline(null); setActiveTab('original') } }
                        )
                      }
                      disabled={reprocess.isPending}
                      icon={reprocess.isPending
                        ? <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} />
                        : <Save size={14} />}
                    >
                      저장 후 재처리
                    </Button>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
        panel={(
          <aside className="ds-side-panel" aria-label="문서 정보">
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
            <VersionHistoryPanel documentId={id} />
          </aside>
        )}
      />
    </Page>
  )
}
