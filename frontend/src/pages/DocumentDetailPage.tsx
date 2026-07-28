import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { AlertTriangle, ArrowLeft, Check, Copy, Download, Loader2, Save, X } from 'lucide-react'
import { useAcceptTagSuggestion, useDeleteChunk, useDismissTagSuggestion, useDocument, useDocumentChunks, useDocumentContent, useDocumentImages, useDocumentPagesText, useDocumentPreview, useDocumentRevisions, useDocumentTables, useDownloadDocument, useProceedDocument, useReprocessDocument, useRestoreRevision, useRetryDocument, useUpdateChunk, useUpdateDocumentTags } from '../hooks/useDocuments'
import { useDocumentQuality, useDocumentRuns, type QualityMetrics } from '../hooks/useDocumentRuns'
import { useCancelRun, useResumeRun, useWorkflowRun } from '../hooks/useWorkflows'
import { STATUS_BADGE_CLASSES, STATUS_LABELS } from '../lib/documentStatus'
import StepTimeline from '../components/workflow/StepTimeline'
import ReprocessModal from '../components/ReprocessModal'
import StructureTab from '../components/document-detail/StructureTab'
import ElementsTab from '../components/document-detail/ElementsTab'
import CleaningChangesTab from '../components/document-detail/CleaningChangesTab'
import DictionaryApplicationsTab from '../components/document-detail/DictionaryApplicationsTab'
import PiiDetectionsTab from '../components/document-detail/PiiDetectionsTab'
import { useUpdateDocumentMetadata, type SecurityLevel } from '../hooks/useDocumentMetadata'
import { useDocumentNodes } from '../hooks/useDocumentStructure'

type TabKey =
  | 'edit' | 'tables' | 'images' | 'chunks' | 'original' | 'quality' | 'history'
  | 'structure' | 'cleaning' | 'dictionary' | 'pii' | 'elements'

// 문서 요약(doc.summary)·추천 태그는 분석 워크플로우 산출물이라 탭이 아니라
// 왼쪽 메타데이터 패널로 이동했다 — 나머지는 전부 전처리 워크플로우 산출물
// (사용자 확인 2026-07-20, "왼쪽 패널 확장으로 진행해줘").
const TABS: { key: TabKey; label: string; pdfOnly?: boolean }[] = [
  { key: 'original', label: '원문 대조' },
  { key: 'structure', label: '구조' },
  // Docling 도입 설계서(2026-07-23) Phase 4 — Docling 엔진(PDF 전용)으로 처리된
  // 문서에서만 의미가 있다. 탭 자체는 pdfOnly로 PDF 문서에만 노출하고(다른
  // pdfOnly 탭과 동일한 기존 게이팅 메커니즘 재사용), 실제로 Docling 결과가
  // 없는 PDF(legacy 엔진)는 ElementsTab이 빈 상태 메시지를 보여준다 — "표" 탭이
  // 표가 0개일 때도 그냥 빈 메시지를 보여주는 것과 동일한 원칙.
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

const QUALITY_STATUS_LABELS: Record<string, string> = {
  SUCCESS: '통과', SUCCESS_WITH_WARNING: '경고와 함께 통과',
  REVIEW_REQUIRED: '검토 필요', PARTIAL_FAILURE: '부분 실패', FAILURE: '실패',
}

// REVIEW_REQUIRED는 실제 품질 경고 때문일 수도, 이 워크플로우의 "모든 문서
// 검토" 정책 때문일 수도 있다 — 후자인데 점수가 100점이어도 그냥 "검토 필요"
// 배지(주황색)만 뜨면 마치 문제가 있는 것처럼 오해하기 쉽다(사용자 확인
// 2026-07-21, "품질이 100점인데... 검토 필요라는 문구는 오해를 발생시킬 수
// 있다"). 경고가 실제로 있을 때만 경고 색/문구를 쓰고, 정책만으로 검토가
// 걸린 경우는 중립색 + "정책상 검토"로 구분한다.
function qualityStatusDisplay(
  status: string, warningCount: number,
): { label: string; badgeClass: string } {
  if (status === 'SUCCESS') return { label: '통과', badgeClass: 'bg-success' }
  if (status === 'FAILURE') return { label: '실패', badgeClass: 'bg-danger' }
  if (status === 'REVIEW_REQUIRED' && warningCount === 0) {
    return { label: '검토 대기(정책)', badgeClass: 'bg-information' }
  }
  return { label: QUALITY_STATUS_LABELS[status] ?? status, badgeClass: 'bg-warning' }
}

const QUALITY_CATEGORY_LABELS: Record<string, string> = {
  textExtraction: '텍스트 추출', ocr: 'OCR', structure: '구조 분석',
  normalization: '정규화', chunking: '청킹',
}

// 경고 카테고리 → 실제로 확인할 수 있는 탭. textExtraction/ocr은 추출된 원문
// 텍스트 자체의 문제라 원문 대조 탭에서, structure는 구조 탭에서, chunking은
// 청크 탭(길이 기준 경고 청크가 이미 강조 표시됨)에서 확인한다(사용자 확인
// 2026-07-21, "경고에 있는 사항들은 네비게이션 기능을 넣어서").
const QUALITY_WARNING_TAB: Record<string, TabKey> = {
  textExtraction: 'original', ocr: 'original', structure: 'structure',
  chunking: 'chunks', chunking_short: 'chunks', chunking_long: 'chunks',
}

// quality_blocks.py의 QualityCheckBlock.run()이 계산해 QualityReport.metrics에
// 저장하는 수치들 — 점수만으로는 알 수 없는 "왜 이 점수인지" 근거를 카테고리별로
// 보여준다(사용자 확인 2026-07-21, "품질값에 대한 근거가 필요할듯하다").
function qualityEvidenceText(category: string, metrics: QualityMetrics): string {
  switch (category) {
    case 'textExtraction':
      return `추출된 텍스트 ${metrics.text_chars ?? '-'}자, 깨진 문자 비율 ${((metrics.broken_char_ratio ?? 0) * 100).toFixed(1)}%`
    case 'ocr':
      return metrics.ocr === 100 ? 'OCR 미사용 또는 신뢰도 정보 없음' : 'OCR 신뢰도 기준 미달'
    case 'structure':
      return `구조 노드 ${metrics.node_count ?? '-'}개, 빈 페이지 비율 ${((metrics.empty_page_ratio ?? 0) * 100).toFixed(1)}%`
    case 'normalization':
      return `사전 적용 ${metrics.dictionary_application_count ?? 0}건 (정보성 지표 — 0건도 정상)`
    case 'chunking':
      return `생성된 청크 ${metrics.chunk_count ?? '-'}개`
    default:
      return ''
  }
}

const RUN_TRIGGER_LABELS: Record<string, string> = {
  UPLOAD: '업로드', MANUAL: '수동 실행', REPROCESS: '부분 재처리', COLLECTION_REPROCESS: '컬렉션 재처리',
}

const RUN_STATUS_BADGE: Record<string, string> = {
  QUEUED: 'bg-gray', RUNNING: 'bg-information', COMPLETED: 'bg-success',
  FAILED: 'bg-danger', CANCELLED: 'bg-gray', WAITING_REVIEW: 'bg-warning',
}

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

const PROCESSING_STATUSES = new Set([
  'QUEUED', 'INGESTING', 'PARSING', 'STRUCTURING',
  'NORMALIZING', 'CHUNKING', 'EMBEDDING', 'UPLOADING',
  'VALIDATING', 'MASKING',
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
      <span style={{ fontSize: 13, minWidth: 0, overflowWrap: 'anywhere', wordBreak: 'break-word' }}>
        {children}
      </span>
    </div>
  )
}

function CopyableValue({ value, display }: { value: string; display: string }) {
  const [copied, setCopied] = useState(false)
  const handleCopy = async () => {
    await navigator.clipboard.writeText(value)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
      <span style={{ fontFamily: 'monospace', fontSize: 11, overflowWrap: 'anywhere', wordBreak: 'break-all' }}>
        {display}
      </span>
      <button
        onClick={handleCopy}
        title="전체 값 복사"
        className="krds-btn text small"
        style={{ cursor: 'pointer', padding: 2, display: 'inline-flex', alignItems: 'center' }}
      >
        {copied ? <Check size={12} style={{ color: '#16a34a' }} /> : <Copy size={12} />}
      </button>
    </span>
  )
}

// 메타 정보 생성 설계서(2026-07-23) Phase 2 — author/organization/
// source_system은 문서 내용에서 자동 생성할 수 없어 사용자가 직접 입력해야
// 채워진다. 청크/요소 탭의 편집 UX(버튼→입력→저장/취소)와 동일한 패턴.
function EditableMetaField({
  label, value, placeholder = '미입력', onSave,
}: { label: string; value: string | null; placeholder?: string; onSave: (value: string) => void }) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(value ?? '')

  if (!editing) {
    return (
      <Row label={label}>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
          <span style={{ color: value ? 'inherit' : 'var(--color-text-muted)' }}>
            {value || placeholder}
          </span>
          <button
            onClick={() => { setDraft(value ?? ''); setEditing(true) }}
            style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0, color: 'var(--color-primary)', fontSize: 12 }}
          >
            편집
          </button>
        </span>
      </Row>
    )
  }

  return (
    <Row label={label}>
      <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          autoFocus
          style={{ fontSize: 12, border: '1px solid #e2e8f0', borderRadius: 4, padding: '2px 8px', width: 160 }}
        />
        <button
          onClick={() => { onSave(draft); setEditing(false) }}
          aria-label={`${label} 저장`}
          style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0, display: 'inline-flex' }}
        >
          <Save size={14} />
        </button>
        <button
          onClick={() => setEditing(false)}
          aria-label={`${label} 편집 취소`}
          style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0, display: 'inline-flex' }}
        >
          <X size={14} />
        </button>
      </span>
    </Row>
  )
}

const SECURITY_LEVEL_OPTIONS: SecurityLevel[] = ['Public', 'Internal', 'Confidential']

function SecurityLevelField({
  value, onSave,
}: { value: string | null; onSave: (value: SecurityLevel | '') => void }) {
  return (
    <Row label="보안 등급">
      <select
        value={value ?? ''}
        onChange={(e) => onSave(e.target.value as SecurityLevel | '')}
        style={{ fontSize: 12, border: '1px solid #e2e8f0', borderRadius: 4, padding: '2px 8px' }}
      >
        <option value="">미입력</option>
        {SECURITY_LEVEL_OPTIONS.map((level) => (
          <option key={level} value={level}>{level}</option>
        ))}
      </select>
    </Row>
  )
}

export default function DocumentDetailPage() {
  const { id = '', projectId } = useParams<{ id: string; projectId?: string }>()
  const navigate = useNavigate()
  const backTo = projectId ? `/projects/${projectId}/documents` : '/documents'
  const { data: doc, isLoading, isError } = useDocument(id)
  const [activeTab, setActiveTab] = useState<TabKey>('original')
  // 품질 탭의 "너무 짧은/큰 청크" 경고를 클릭했을 때 청크 탭으로 이동만 하는 게
  // 아니라 실제 문제 청크로 스크롤하기 위한 목표 id 목록(사용자 확인 2026-07-21,
  // "청크텝에서 확인이아니라 문제가 되는 청크로 바로 이동하게 해야지").
  const [highlightChunkIds, setHighlightChunkIds] = useState<string[] | null>(null)
  const needsContent = activeTab === 'edit' || activeTab === 'original'
  const { data: content, isLoading: isContentLoading, isError: isContentError } = useDocumentContent(id, needsContent)
  const { data: tablesResult, isLoading: isTablesLoading, isError: isTablesError } = useDocumentTables(id, activeTab === 'tables')
  const { data: imagesResult, isLoading: isImagesLoading, isError: isImagesError } = useDocumentImages(id, activeTab === 'images')
  // 청크 탭을 열지 않아도 왼쪽 RAG 현황 패널이 청크 개수를 보여줘야 하므로
  // INDEXED 상태가 되면 곧바로 가져온다(탭 진입 시점까지 미루지 않음). WAITING_REVIEW도
  // 포함 — 검토 게이트에 걸린 문서도 chunk_split이 이미 만든(아직 미임베딩) 청크를
  // 패널에서 바로 보여줘야 한다(사용자 확인 2026-07-21, "청크가 0으로 나온다").
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

  useEffect(() => {
    if (activeTab === 'edit' && content && editBaseline === null) {
      setEditedContent(content.full_text)
      setEditBaseline(content.full_text)
    }
  }, [activeTab, content, editBaseline])

  // 품질 경고 클릭으로 청크 탭에 들어왔을 때 실제 문제 청크로 스크롤한다 — 청크
  // 탭으로만 이동시키면 결국 사용자가 목록을 훑어 찾아야 하는 문제가 그대로다
  // (사용자 확인 2026-07-21).
  useEffect(() => {
    if (activeTab !== 'chunks' || !highlightChunkIds?.length || !chunksResult) return
    const targetId = highlightChunkIds.find((cid) => chunksResult.chunks.some((c) => c.id === cid))
    if (!targetId) return
    const el = document.getElementById(`chunk-row-${targetId}`)
    el?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }, [activeTab, highlightChunkIds, chunksResult])

  useEffect(() => {
    if (doc?.status === 'WAITING_REVIEW' && activeTab === 'original') {
      setActiveTab('quality')
    }
  }, [doc?.status, activeTab])

  const isProcessing = doc && PROCESSING_STATUSES.has(doc.status)
  // "전처리 단계" 패널의 데이터 소스 — ProcessingJob은 13개 블록 중 text_extract만
  // 기록해 그 외 블록 진행이 전혀 안 보였다(사용자 확인 2026-07-20, 이슈 4). DAG
  // 실행기가 남기는 WorkflowRun의 실제 스텝별 진행 상황으로 대체한다.
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
      `}</style>
      <button onClick={() => navigate(backTo)} className="krds-btn text small" style={{ marginBottom: 'var(--space-4)', display: 'inline-flex', alignItems: 'center', gap: 6, background: 'none', border: 'none', cursor: 'pointer', color: 'var(--color-text-muted)', fontSize: 14, padding: 0 }}>
        <ArrowLeft size={16} /> 문서 목록
      </button>

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
      <div style={{ maxWidth: 640 }}>
        <Row label="상태">
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
            <span className={`krds-badge small ${STATUS_BADGE_CLASSES[doc.status] ?? 'bg-gray'}`}>
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
        {/* 메타 정보 생성 설계서(2026-07-23) — title/language/category/page_count는
            문서 내용에서 자동 생성(Phase 1)되므로 읽기 전용, author/organization/
            security_level/source_system은 자동 생성이 불가능해(Phase 2) 사용자가
            직접 입력하는 편집 필드로 제공한다. */}
        <Row label="제목">{doc.title || doc.original_filename}</Row>
        <Row label="언어">{doc.language ?? '미판별'}</Row>
        <Row label="분류">{doc.category ?? '미분류'}</Row>
        <Row label="페이지 수">{doc.page_count ?? '-'}</Row>
        {/* 메타 정보 생성.txt 1절 — checksum/parser_version/source_path/file_type은
            기존 file_hash/pipeline_version/minio_key/mime_type 컬럼을 스펙 필드명으로
            노출한 값이라 읽기 전용(2026-07-24). */}
        <Row label="체크섬">
          {doc.checksum
            ? <CopyableValue value={doc.checksum} display={`${doc.checksum.slice(0, 16)}…`} />
            : '-'}
        </Row>
        <Row label="저장 경로">
          {doc.source_path
            ? <CopyableValue value={doc.source_path} display={doc.source_path} />
            : '-'}
        </Row>
        <Row label="파일 형식">{doc.file_type ?? '-'}</Row>
        <EditableMetaField
          label="문서 작성일"
          value={doc.document_created_at ? doc.document_created_at.slice(0, 10) : null}
          placeholder="자동 추출 불가 — 직접 입력(YYYY-MM-DD)"
          onSave={(value) => updateMetadata.mutate({ documentId: id, document_created_at: value })}
        />
        <EditableMetaField
          label="작성자"
          value={doc.author}
          onSave={(value) => updateMetadata.mutate({ documentId: id, author: value })}
        />
        <EditableMetaField
          label="부서/기관"
          value={doc.organization}
          onSave={(value) => updateMetadata.mutate({ documentId: id, organization: value })}
        />
        <SecurityLevelField
          value={doc.security_level}
          onSave={(value) => updateMetadata.mutate({ documentId: id, security_level: value || null })}
        />
        <EditableMetaField
          label="출처 시스템"
          value={doc.source_system}
          onSave={(value) => updateMetadata.mutate({ documentId: id, source_system: value })}
        />
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
              id="document_tag_input"
              name="document_tag_input"
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
        {doc.metadata_status === 'GENERATING' && (
          <Row label="추천 태그">
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--color-text-muted)' }}>
              <Loader2 size={12} style={{ animation: 'spin 1s linear infinite' }} />
              자동 추출 중...
            </span>
          </Row>
        )}
        {!!doc.suggested_tags?.length && (
          <Row label="추천 태그">
            <span style={{ display: 'inline-flex', flexWrap: 'wrap', gap: 6, alignItems: 'center' }}>
              {doc.suggested_tags.map((tag) => {
                // 추천 태그는 수락해도 목록에서 사라지지 않는다(백엔드가
                // suggested_tags를 그대로 둠, 사용자 확인 2026-07-20) — 이미
                // 추가된 항목은 "+"를 "✓ 추가됨"으로 바꿔 중복 클릭을 막는다.
                const alreadyAdded = (doc.tags ?? []).includes(tag)
                return (
                  <span
                    key={tag}
                    className="krds-badge small"
                    style={{
                      display: 'inline-flex', alignItems: 'center', gap: 4,
                      border: alreadyAdded ? '1px solid var(--color-success, #16a34a)' : '1px dashed #94a3b8',
                      background: 'transparent', color: 'var(--color-text-muted)',
                    }}
                  >
                    {tag}
                    {alreadyAdded ? (
                      <span
                        title="이미 태그로 추가됨"
                        style={{ color: 'var(--color-success, #16a34a)', lineHeight: 1, fontWeight: 700 }}
                      >
                        ✓
                      </span>
                    ) : (
                      <button
                        onClick={() => acceptSuggestion.mutate({ docId: id, tag })}
                        aria-label={`추천 태그 ${tag} 추가`}
                        title="태그로 추가"
                        style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0, color: 'var(--color-success, #16a34a)', lineHeight: 1, fontWeight: 700 }}
                      >
                        +
                      </button>
                    )}
                    <button
                      onClick={() => dismissSuggestion.mutate({ docId: id, tag })}
                      aria-label={`추천 태그 ${tag} 무시`}
                      title="제안 무시"
                      style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0, color: 'inherit', lineHeight: 1 }}
                    >
                      ×
                    </button>
                  </span>
                )
              })}
            </span>
          </Row>
        )}
      </div>

      {isReady && (
        <div style={{ marginTop: 'var(--space-6)', maxWidth: 640 }}>
          <h2 style={{ fontSize: 14, fontWeight: 600, marginBottom: 'var(--space-2)' }}>
            분석 요약
          </h2>
          {/* summary_status가 PENDING인 것만으로는 "곧 생성될 것"과 "이 문서엔
              생성 주체가 없어 영영 안 나올 것"을 구분할 수 없다 — 분석 워크플로우
              그래프에 요약 블록이 없으면 후자인데도 스피너가 계속 돌았다(사용자
              확인 2026-07-22, "생성이 안되는 거면... 맨트가 안나와야지"). 지금
              실제로 분석이 도는 중(ANALYZING)일 때만 "생성 중"으로 보여준다. */}
          {isAnalyzing && (doc.summary_status === 'PENDING' || doc.summary_status === 'GENERATING') && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--color-text-muted)', fontSize: 13 }}>
              <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} />
              문서 요약을 생성하는 중입니다...
            </div>
          )}
          {!isAnalyzing && (doc.summary_status === 'PENDING' || doc.summary_status === 'GENERATING') && (
            <p style={{ color: 'var(--color-text-muted)', fontSize: 13, margin: 0 }}>
              생성된 요약이 없습니다.
            </p>
          )}
          {doc.summary_status === 'FAILED' && (
            <p style={{ color: 'var(--color-text-muted)', fontSize: 13, margin: 0 }}>
              요약을 생성하지 못했습니다.
            </p>
          )}
          {doc.summary_status === 'DONE' && (
            <p style={{ fontSize: 13, lineHeight: 1.7, whiteSpace: 'pre-wrap', margin: 0, color: 'var(--color-accent)' }}>
              {doc.summary || '요약 내용이 없습니다.'}
            </p>
          )}
        </div>
      )}

      {showWorkflowTabs && (
        <div style={{ marginTop: 'var(--space-6)', maxWidth: 640 }}>
          <h2 style={{ fontSize: 14, fontWeight: 600, marginBottom: 'var(--space-2)' }}>
            RAG 현황
          </h2>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, fontSize: 13 }}>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
              <span style={{ width: 64, flexShrink: 0, color: 'var(--color-text-muted)' }}>청크</span>
              {chunksResult ? (
                <>
                  <span>{chunksResult.chunks.length}개</span>
                  {chunksResult.chunks.some((c) => c.disabled) && (
                    <span style={{ color: 'var(--color-text-muted)' }}>
                      (검색 제외 {chunksResult.chunks.filter((c) => c.disabled).length}개)
                    </span>
                  )}
                  <span style={{ color: 'var(--color-text-muted)' }}>
                    · 조회 {chunksResult.chunks.reduce((sum, c) => sum + c.hit_count, 0)}회
                  </span>
                </>
              ) : (
                <span style={{ color: 'var(--color-text-muted)' }}>불러오는 중...</span>
              )}
              <button
                onClick={() => setActiveTab('chunks')}
                className="krds-btn text xsmall"
                style={{ padding: 0, cursor: 'pointer' }}
              >
                자세히
              </button>
            </span>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
              <span style={{ width: 64, flexShrink: 0, color: 'var(--color-text-muted)' }}>품질</span>
              {qualityReport ? (
                <>
                  <span className={`krds-badge xsmall ${qualityStatusDisplay(qualityReport.status, qualityReport.warnings?.length ?? 0).badgeClass}`}>
                    {qualityStatusDisplay(qualityReport.status, qualityReport.warnings?.length ?? 0).label}
                  </span>
                  {qualityReport.overall_score != null && (
                    <span style={{ color: 'var(--color-text-muted)' }}>{qualityReport.overall_score.toFixed(1)}점</span>
                  )}
                  {!!qualityReport.warnings?.length && (
                    <span style={{ color: '#b45309' }}>경고 {qualityReport.warnings.length}건</span>
                  )}
                </>
              ) : (
                <span style={{ color: 'var(--color-text-muted)' }}>리포트 없음</span>
              )}
              <button
                onClick={() => setActiveTab('quality')}
                className="krds-btn text xsmall"
                style={{ padding: 0, cursor: 'pointer' }}
              >
                자세히
              </button>
            </span>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
              <span style={{ width: 64, flexShrink: 0, color: 'var(--color-text-muted)' }}>최근 실행</span>
              {latestRun ? (
                <>
                  <span className={`krds-badge xsmall ${RUN_STATUS_BADGE[latestRun.status] ?? 'bg-gray'}`}>
                    {latestRun.status}
                  </span>
                  <span>{RUN_TRIGGER_LABELS[latestRun.trigger] ?? latestRun.trigger}</span>
                  <span style={{ color: 'var(--color-text-muted)' }}>
                    {latestRun.started_at ? new Date(latestRun.started_at).toLocaleString('ko-KR') : '-'}
                  </span>
                </>
              ) : (
                <span style={{ color: 'var(--color-text-muted)' }}>실행 이력 없음</span>
              )}
              <button
                onClick={() => setActiveTab('history')}
                className="krds-btn text xsmall"
                style={{ padding: 0, cursor: 'pointer' }}
              >
                자세히
              </button>
            </span>
          </div>
        </div>
      )}

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
                          문서 메타정보
                        </summary>
                        <div className="markdown-body" style={{ marginTop: 8, fontSize: 12 }}>
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>
                            {[
                              `**제목**: ${doc.title || doc.original_filename}`,
                              `**언어**: ${doc.language ?? '미판별'}`,
                              `**분류**: ${doc.category ?? '미분류'}`,
                              `**페이지 수**: ${doc.page_count ?? '-'}`,
                              `**작성자**: ${doc.author ?? '미입력'}`,
                              `**부서/기관**: ${doc.organization ?? '미입력'}`,
                              `**보안 등급**: ${doc.security_level ?? '미입력'}`,
                              `**출처 시스템**: ${doc.source_system ?? '미입력'}`,
                            ].join('\n\n')}
                          </ReactMarkdown>
                        </div>
                      </details>
                      <details style={{ flexShrink: 0, marginBottom: 'var(--space-3)', fontSize: 12 }}>
                        <summary style={{ cursor: 'pointer', color: 'var(--color-text-muted)', userSelect: 'none' }}>
                          구조 ({editNodesResult?.nodes.length ?? 0}개 노드)
                        </summary>
                        <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 6 }}>
                          {editNodesResult && editNodesResult.nodes.length > 0 ? (() => {
                            const counts = editNodesResult.nodes.reduce<Record<string, number>>((acc, n) => {
                              acc[n.node_type] = (acc[n.node_type] ?? 0) + 1
                              return acc
                            }, {})
                            return (
                              <span style={{ color: 'var(--color-text-muted)' }}>
                                제목 {(counts.HEADING ?? 0) + (counts.SECTION ?? 0)} · 문단 {counts.PARAGRAPH ?? 0} · 표 {counts.TABLE ?? 0} · 목록 {counts.LIST ?? 0}
                              </span>
                            )
                          })() : (
                            <span style={{ color: 'var(--color-text-muted)' }}>구조 분석 결과가 없습니다.</span>
                          )}
                          <button
                            type="button"
                            onClick={() => setActiveTab('structure')}
                            className="krds-btn text small"
                            style={{ cursor: 'pointer', alignSelf: 'flex-start', padding: 0 }}
                          >
                            구조 탭에서 전체 보기
                          </button>
                        </div>
                      </details>
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
                      {imagesResult.detected_count != null
                        && imagesResult.detected_count > imagesResult.images.length && (
                        <p style={{ fontSize: 12, color: 'var(--color-text-muted)', margin: 0 }}>
                          {imagesResult.detected_count}개 감지됨 · {imagesResult.images.length}개 표시
                          (너무 작거나 중복된 이미지 {imagesResult.detected_count - imagesResult.images.length}개 제외)
                        </p>
                      )}
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
                        총 {chunksResult.chunks.length}개 청크
                        {(() => {
                          const tokenCounts = chunksResult.chunks.map((c) => c.token_count).filter((t): t is number => t != null)
                          if (!tokenCounts.length) return null
                          const avg = Math.round(tokenCounts.reduce((a, b) => a + b, 0) / tokenCounts.length)
                          return ` · 평균 ${avg}토큰`
                        })()}
                        . 텍스트를 수정하면 해당 청크만 다시 임베딩되고,
                        "검색 제외"된 청크는 검색·채팅에서 사용되지 않습니다.
                      </p>
                      {chunksResult.chunks.some((c) => !c.embedded) && (
                        <p style={{ fontSize: 12, color: '#b45309', margin: 0 }}>
                          아직 임베딩되지 않은 미리보기입니다(검토 승인 후 벡터 저장이 진행됩니다). 이 상태에서는
                          수정·검색 제외·삭제를 할 수 없고, 품질 경고에서 언급된 청크 길이를 확인하는 용도로만 쓸 수 있습니다.
                          아래 굵게 표시된 청크는 너무 짧거나(50자 미만) 너무 깁니다(2000자 초과).
                        </p>
                      )}
                      {chunksResult.chunks.map((chunk) => {
                        const isTooShort = chunk.text.length < 50
                        const isTooLong = chunk.text.length > 2000
                        const isJumpTarget = !!highlightChunkIds?.includes(chunk.id)
                        return (
                        <div
                          key={chunk.id}
                          id={`chunk-row-${chunk.id}`}
                          style={{
                            border: isJumpTarget ? '2px solid var(--color-accent)'
                              : (isTooShort || isTooLong) ? '1px solid #fde68a' : '1px solid #e2e8f0',
                            borderRadius: 'var(--radius-md)',
                            padding: 'var(--space-3)', background: (isTooShort || isTooLong) ? '#fffbeb' : '#fff',
                            opacity: chunk.disabled ? 0.55 : 1,
                          }}
                        >
                          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 'var(--space-2)' }}>
                            <span style={{ fontSize: 12, fontWeight: 600 }}>
                              청크 #{chunk.chunk_index + 1}
                              {isPdfDoc && chunk.page_number ? ` · ${chunk.page_number}쪽` : ''}
                            </span>
                            <span style={{ fontSize: 11, color: (isTooShort || isTooLong) ? '#b45309' : 'var(--color-text-muted)' }}>
                              {chunk.text.length}자{isTooShort ? ' · 너무 짧음' : isTooLong ? ' · 너무 김' : ''}
                            </span>
                            {!chunk.embedded && <span className="krds-badge small bg-warning">임베딩 전 미리보기</span>}
                            {chunk.edited && <span className="krds-badge small bg-information">수정됨</span>}
                            {chunk.disabled && <span className="krds-badge small bg-gray">검색 제외</span>}
                            {chunk.chunk_type && <span className="krds-badge small bg-gray">{chunk.chunk_type}</span>}
                            {chunk.token_count != null && (
                              <span style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
                                토큰 ~{chunk.token_count}
                              </span>
                            )}
                            {!!chunk.section_path?.length && (
                              <span style={{ fontSize: 11, color: 'var(--color-text-muted)' }} title="섹션 경로">
                                {chunk.section_path.join(' > ')}
                              </span>
                            )}
                            {!!chunk.keywords?.length && (
                              <span style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
                                #{chunk.keywords.join(' #')}
                              </span>
                            )}
                            {chunk.embedding_model && (
                              <span style={{ fontSize: 11, color: 'var(--color-text-muted)' }} title="임베딩 모델">
                                {chunk.embedding_model}
                                {chunk.version ? ` (v${chunk.version})` : ''}
                              </span>
                            )}
                            {chunk.language && (
                              <span style={{ fontSize: 11, color: 'var(--color-text-muted)' }} title="언어">
                                {chunk.language}
                              </span>
                            )}
                            {chunk.source_file && (
                              <span style={{ fontSize: 11, color: 'var(--color-text-muted)' }} title="원본 파일명">
                                📄 {chunk.source_file}
                              </span>
                            )}
                            {chunk.embedded && (
                              <span
                                title="검색/채팅 응답에서 이 청크가 실제로 반환된 횟수"
                                style={{
                                  fontSize: 11,
                                  color: chunk.hit_count > 0 ? 'var(--color-text-muted)' : '#b45309',
                                }}
                              >
                                조회 {chunk.hit_count}회{chunk.hit_count === 0 ? ' · 미조회' : ''}
                              </span>
                            )}
                            <span style={{ flex: 1 }} />
                            {chunk.page_number != null && (
                              <button
                                onClick={() => { setOriginalPage(chunk.page_number as number); setActiveTab('original') }}
                                className="krds-btn text small"
                                style={{ cursor: 'pointer' }}
                              >
                                원문 대조에서 보기
                              </button>
                            )}
                            {chunk.embedded && chunkEditId !== chunk.id && (
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
                          {(chunk.prev_chunk_id || chunk.next_chunk_id) && (
                            <div style={{ display: 'flex', gap: 12, fontSize: 11, color: 'var(--color-text-muted)', marginBottom: 'var(--space-2)' }}>
                              {chunk.prev_chunk_id && (
                                <button
                                  onClick={() => document.getElementById(`chunk-row-${chunk.prev_chunk_id}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })}
                                  className="krds-btn text small"
                                  style={{ cursor: 'pointer', fontSize: 11, padding: 0 }}
                                >
                                  ◀ 이전 청크
                                </button>
                              )}
                              {chunk.next_chunk_id && (
                                <button
                                  onClick={() => document.getElementById(`chunk-row-${chunk.next_chunk_id}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })}
                                  className="krds-btn text small"
                                  style={{ cursor: 'pointer', fontSize: 11, padding: 0 }}
                                >
                                  다음 청크 ▶
                                </button>
                              )}
                            </div>
                          )}
                          {chunk.parent_chunk_text && (
                            <div style={{ marginBottom: 'var(--space-2)' }}>
                              <button
                                onClick={() => setExpandedParentChunkId(expandedParentChunkId === chunk.id ? null : chunk.id)}
                                className="krds-btn text small"
                                style={{ cursor: 'pointer', fontSize: 11, padding: 0, color: 'var(--color-text-muted)' }}
                              >
                                {expandedParentChunkId === chunk.id ? '▾' : '▸'} 상위 청크 보기 (Parent Retrieval)
                              </button>
                              {expandedParentChunkId === chunk.id && (
                                <pre style={{
                                  fontSize: 11, lineHeight: 1.6, whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                                  fontFamily: 'inherit', margin: '6px 0 0', padding: 'var(--space-2)',
                                  background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 'var(--radius-sm)',
                                  color: '#475569',
                                }}>
                                  {chunk.parent_chunk_text}
                                </pre>
                              )}
                            </div>
                          )}
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
                        )
                      })}
                    </div>
                  )}
                </>
              )}
              {activeTab === 'original' && (() => {
                const pages = pagesTextResult?.pages ?? []
                const isPdfPreview = previewResult?.kind === 'pdf'
                // 원본이 실제 PDF일 때만 pagesTextResult가 doc.parsed_text(RAG에
                // 쓰인 실제 텍스트)를 페이지 경계로 자른 것이다. DOCX/HWP 등은
                // 변환 미리보기 PDF에서 PyMuPDF로 재추출한 텍스트라 RAG 저장
                // 형태와 다를 수 있어(9항목 펀치리스트 #2/#6), 그 경우 페이지
                // 네비게이션(좌측 미리보기용)은 유지하되 우측 텍스트는 항상
                // content.full_text(Qdrant에 저장된 청크를 그대로 재조립한 것)를
                // 통째로 보여준다.
                const isNativePdf = (doc?.original_filename ?? '').toLowerCase().endsWith('.pdf')
                const hasMultiplePages = new Set(pages.map((p) => p.page_number)).size > 1
                const maxPage = pages.length ? Math.max(...pages.map((p) => p.page_number)) : 1
                const clampedPage = Math.min(Math.max(originalPage, 1), maxPage)
                const currentPageText = isNativePdf && hasMultiplePages
                  ? pages.filter((p) => p.page_number === clampedPage).map((p) => p.text).join('\n\n')
                  : null
                return (
                  <div style={{ display: 'flex', flexDirection: 'column', height: '100%', gap: 'var(--space-2)' }}>
                    {hasMultiplePages && (
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
                          {isNativePdf
                            ? '원본과 파싱 텍스트가 같은 쪽으로 함께 이동합니다'
                            : '원본 미리보기만 페이지 이동합니다 (텍스트는 문서 전체가 표시됩니다)'}
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
                            파싱된 텍스트 (RAG 저장 형태){isNativePdf && hasMultiplePages ? ` (${clampedPage}쪽)` : ''}
                          </p>
                          <ViewModeToggle showJson={showJson} onChange={setShowJson} />
                        </div>
                        <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', border: '1px solid #e2e8f0', borderRadius: 'var(--radius-sm)', padding: 'var(--space-3)', background: showJson ? '#f8fafc' : '#fff' }}>
                          {isContentLoading && (
                            <div style={{ display: 'flex', justifyContent: 'center', padding: 'var(--space-6)' }}>
                              <Loader2 size={20} style={{ animation: 'spin 1s linear infinite', color: 'var(--color-text-muted)' }} />
                            </div>
                          )}
                          {!isContentLoading && showJson && (
                            <pre style={{
                              fontSize: 12, lineHeight: 1.6, whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                              fontFamily: 'monospace', margin: 0,
                            }}>
                              {toBlocksJson(currentPageText ?? content?.full_text ?? '')}
                            </pre>
                          )}
                          {!isContentLoading && !showJson && (
                            <div className="markdown-body" style={{ fontSize: 13, lineHeight: 1.7 }}>
                              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                                {currentPageText ?? content?.full_text ?? ''}
                              </ReactMarkdown>
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                )
              })()}

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
                <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
                  {!qualityReport && (
                    <p style={{ color: 'var(--color-text-muted)', fontSize: 13, margin: 0 }}>
                      아직 품질 리포트가 없습니다.
                    </p>
                  )}
                  {qualityReport && (
                    <>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
                        <span style={{ fontSize: 32, fontWeight: 700 }}>
                          {qualityReport.overall_score != null ? qualityReport.overall_score.toFixed(1) : '-'}
                        </span>
                        <span className={`krds-badge small ${qualityStatusDisplay(qualityReport.status, qualityReport.warnings?.length ?? 0).badgeClass}`}>
                          {qualityStatusDisplay(qualityReport.status, qualityReport.warnings?.length ?? 0).label}
                        </span>
                      </div>
                      {qualityReport.scores && (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
                          {Object.entries(qualityReport.scores).map(([category, score]) => (
                            <div key={category}>
                              <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
                                <span style={{ fontSize: 12, width: 120, flexShrink: 0, color: 'var(--color-text-muted)' }}>
                                  {QUALITY_CATEGORY_LABELS[category] ?? category}
                                </span>
                                <div style={{ flex: 1, height: 8, background: '#e2e8f0', borderRadius: 4, overflow: 'hidden' }}>
                                  <div style={{
                                    width: `${Math.max(0, Math.min(100, score))}%`, height: '100%',
                                    background: score >= 70 ? '#16a34a' : score >= 40 ? '#d97706' : '#dc2626',
                                  }} />
                                </div>
                                <span style={{ fontSize: 12, width: 36, textAlign: 'right' }}>{score.toFixed(0)}</span>
                              </div>
                              {qualityReport.metrics && (
                                <p style={{ fontSize: 11, color: 'var(--color-text-muted)', margin: '2px 0 0 132px' }}>
                                  {qualityEvidenceText(category, qualityReport.metrics)}
                                </p>
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                      {!!qualityReport.warnings?.length && (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-1)' }}>
                          <strong style={{ fontSize: 13 }}>경고</strong>
                          {qualityReport.warnings.map((w, i) => {
                            const category = qualityReport.warning_categories?.[i]
                            const targetTab = category ? QUALITY_WARNING_TAB[category] : undefined
                            const targetChunkIds =
                              category === 'chunking_short' ? qualityReport.metrics?.short_chunk_ids
                              : category === 'chunking_long' ? qualityReport.metrics?.long_chunk_ids
                              : undefined
                            return (
                              <button
                                key={i}
                                type="button"
                                onClick={() => {
                                  if (!targetTab) return
                                  setHighlightChunkIds(targetChunkIds?.length ? targetChunkIds : null)
                                  setActiveTab(targetTab)
                                }}
                                disabled={!targetTab}
                                style={{
                                  display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: '#b45309',
                                  background: 'none', border: 'none', padding: 0, textAlign: 'left', width: '100%',
                                  cursor: targetTab ? 'pointer' : 'default',
                                }}
                              >
                                <AlertTriangle size={13} style={{ flexShrink: 0 }} />
                                <span style={{ flex: 1 }}>{String(w)}</span>
                                {targetTab && (
                                  <span style={{ fontSize: 11, textDecoration: 'underline', flexShrink: 0 }}>
                                    {targetChunkIds?.length
                                      ? '문제 청크로 이동 →'
                                      : `${TABS.find((t) => t.key === targetTab)?.label ?? targetTab} 탭에서 확인 →`}
                                  </span>
                                )}
                              </button>
                            )
                          })}
                        </div>
                      )}
                      {qualityReport.review_note && (
                        <div style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
                          <strong>검토 의견:</strong> {qualityReport.review_note}
                        </div>
                      )}
                    </>
                  )}
                  {isWaitingReview && latestRun && (
                    <div style={{ display: 'flex', gap: 'var(--space-2)', paddingTop: 'var(--space-3)', borderTop: '1px solid #e2e8f0' }}>
                      <button
                        onClick={() => cancelRun.mutate(latestRun.id)}
                        disabled={cancelRun.isPending || resumeRun.isPending}
                        className="krds-btn secondary medium"
                        style={{ cursor: 'pointer' }}
                      >
                        반려
                      </button>
                      <button
                        onClick={() => resumeRun.mutate(latestRun.id)}
                        disabled={cancelRun.isPending || resumeRun.isPending}
                        className="krds-btn primary medium"
                        style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}
                      >
                        {resumeRun.isPending && <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} />}
                        승인 후 계속 진행
                      </button>
                    </div>
                  )}
                  {(cancelRun.isError || resumeRun.isError) && (
                    <p style={{ color: '#dc2626', fontSize: 12, margin: 0 }}>작업을 처리하지 못했습니다.</p>
                  )}
                </div>
              )}

              {activeTab === 'history' && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
                  {!runsData?.runs.length && (
                    <p style={{ color: 'var(--color-text-muted)', fontSize: 13, margin: 0 }}>
                      처리 이력이 없습니다.
                    </p>
                  )}
                  {!!runsData?.runs.length && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                      {runsData.runs.map((run) => (
                        <button
                          key={run.id}
                          onClick={() => setSelectedRunId(run.id)}
                          style={{
                            display: 'flex', alignItems: 'center', gap: 'var(--space-2)', textAlign: 'left',
                            padding: 'var(--space-1) var(--space-2)', fontSize: 12, border: '1px solid #e2e8f0',
                            borderRadius: 'var(--radius-sm)', cursor: 'pointer',
                            background: run.id === historyRunId ? '#eff6ff' : '#fff',
                          }}
                        >
                          <span className={`krds-badge xsmall ${RUN_STATUS_BADGE[run.status] ?? 'bg-gray'}`}>
                            {run.status}
                          </span>
                          <span>{RUN_TRIGGER_LABELS[run.trigger] ?? run.trigger}</span>
                          <span style={{ color: 'var(--color-text-muted)' }}>
                            {run.started_at ? new Date(run.started_at).toLocaleString('ko-KR') : '-'}
                          </span>
                          {run.dictionary_version != null && (
                            <span style={{ color: 'var(--color-text-muted)' }}>사전 v{run.dictionary_version}</span>
                          )}
                        </button>
                      ))}
                    </div>
                  )}
                  {historyRunDetail && (
                    <StepTimeline
                      steps={historyRunDetail.steps}
                      renderStepActions={(step) => (
                        <button
                          onClick={() => setReprocessModal({ blockInstanceId: step.block_instance_id })}
                          className="krds-btn text xsmall"
                          style={{ cursor: 'pointer' }}
                        >
                          이 블록부터 재처리
                        </button>
                      )}
                    />
                  )}
                </div>
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
