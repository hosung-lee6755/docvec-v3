import type { QualityMetrics } from '../../hooks/useDocumentRuns'
import type { DocumentLanguage } from '../../hooks/useDocumentMetadata'
import type { DocumentChunk2 } from '../../hooks/useDocuments'

export type TabKey =
  | 'edit' | 'tables' | 'images' | 'chunks' | 'original' | 'quality' | 'history'
  | 'structure' | 'cleaning' | 'dictionary' | 'pii' | 'elements'

// Quality status display helpers
const QUALITY_STATUS_LABELS: Record<string, string> = {
  SUCCESS: '통과', SUCCESS_WITH_WARNING: '경고와 함께 통과',
  REVIEW_REQUIRED: '검토 필요', PARTIAL_FAILURE: '부분 실패', FAILURE: '실패',
}

export function qualityStatusDisplay(
  status: string, warningCount: number,
): { label: string; badgeClass: string } {
  if (status === 'SUCCESS') return { label: '통과', badgeClass: 'bg-success' }
  if (status === 'FAILURE') return { label: '실패', badgeClass: 'bg-danger' }
  if (status === 'REVIEW_REQUIRED' && warningCount === 0) {
    return { label: '검토 대기(정책)', badgeClass: 'bg-information' }
  }
  return { label: QUALITY_STATUS_LABELS[status] ?? status, badgeClass: 'bg-warning' }
}

export const QUALITY_CATEGORY_LABELS: Record<string, string> = {
  textExtraction: '텍스트 추출', ocr: 'OCR', structure: '구조 분석',
  normalization: '정규화', chunking: '청킹', sourceRecall: '원문 재현율',
}

export function qualityEvidenceText(category: string, metrics: QualityMetrics): string {
  switch (category) {
    case 'textExtraction':
      return `추출된 텍스트 ${metrics.text_chars ?? '-'}자, 깨진 문자 비율 ${((metrics.broken_char_ratio ?? 0) * 100).toFixed(1)}%`
    case 'ocr':
      return metrics.ocr === 100 ? 'OCR 미사용 또는 신뢰도 정보 없음' : 'OCR 신뢰도 기준 미달'
    case 'structure':
      return `구조 노드 ${metrics.node_count ?? '-'}개, 빈 페이지 비율 ${((metrics.empty_page_ratio ?? 0) * 100).toFixed(1)}%`
    case 'normalization':
      return '이전 버전 리포트의 항목 — 항상 100점인 고정값이며 측정하지 않습니다(현재는 종합점수에서 제외).'
    case 'sourceRecall':
      return `원본 PDF 텍스트 레이어의 ${((metrics.source_recall ?? 0) * 100).toFixed(1)}%가 추출 결과에 있음 (${metrics.source_recall_measured_pages ?? 0}페이지 비교)`
    case 'chunking':
      return `생성된 청크 ${metrics.chunk_count ?? '-'}개`
    default:
      return ''
  }
}

export const RUN_TRIGGER_LABELS: Record<string, string> = {
  UPLOAD: '업로드', MANUAL: '수동 실행', REPROCESS: '재처리', COLLECTION_REPROCESS: '컬렉션 재처리',
  // 전처리가 끝난 뒤 컬렉션의 분석 워크플로우(없으면 표준 분석)로 도는 실행
  AUTO_ANALYSIS: '자동 분석',
}

// 실행 상태를 화면에 보일 한글 이름. 모르는 값은 원래 값을 그대로 보인다.
export const RUN_STATUS_LABELS: Record<string, string> = {
  QUEUED: '대기', RUNNING: '실행 중', COMPLETED: '완료',
  FAILED: '실패', CANCELLED: '취소', WAITING_REVIEW: '검토 대기',
}

export const RUN_STATUS_BADGE: Record<string, string> = {
  QUEUED: 'bg-gray', RUNNING: 'bg-information', COMPLETED: 'bg-success',
  FAILED: 'bg-danger', CANCELLED: 'bg-gray', WAITING_REVIEW: 'bg-warning',
}

// 문서 언어 선택지 — 백엔드 PATCH /documents/{id}/metadata의 language 허용값과 맞춘다.
export const DOCUMENT_LANGUAGE_OPTIONS: { code: DocumentLanguage; label: string }[] = [
  { code: 'ko', label: '한국어' },
  { code: 'en', label: '영어' },
  { code: 'ja', label: '일본어' },
  { code: 'zh', label: '중국어' },
]

// 알 수 없는 코드는 가공하지 않고 그대로 보여 준다(백엔드가 새 언어를 추가했을 때 대비).
export function documentLanguageLabel(code: string): string {
  return DOCUMENT_LANGUAGE_OPTIONS.find((option) => option.code === code)?.label ?? code
}

export const REVISION_SOURCE_LABELS: Record<string, string> = {
  PARSE: '자동 파싱',
  CLEAN: '정제 결과',
  REVIEW_EDIT: '검토 단계 수정',
  RAG_EDIT: 'RAG 데이터 수정',
  RESTORE: '이력 복원',
}

export const QUALITY_WARNING_TAB: Record<string, TabKey> = {
  textExtraction: 'original', ocr: 'original', sourceRecall: 'original', structure: 'structure',
  chunking: 'chunks', chunking_short: 'chunks', chunking_long: 'chunks',
}

export function toBlocksJson(text: string): string {
  const blocks = text.split('\n\n').filter((b) => b.trim().length > 0)
  return JSON.stringify({ blocks }, null, 2)
}

export interface RagRecordSource {
  id: string
  original_filename: string
  title?: string | null
  language?: string | null
  security_level?: string | null
}

/**
 * 검색과 채팅이 실제로 쓰는 RAG 레코드(벡터 DB에 저장된 청크와 그 메타데이터)를 JSON으로 보여 준다.
 * 예전 JSON 보기는 본문을 빈 줄로 잘라 {blocks: [...]}로만 보여 줘, 구조와 요소 정보가 전혀 없었다(2026-11-13).
 * page를 주면 그 쪽에서 시작하는 청크만 담는다.
 */
export function toRagRecordsJson(doc: RagRecordSource, chunks: DocumentChunk2[], page?: number): string {
  const selected = page == null ? chunks : chunks.filter((c) => c.page_number === page)
  return JSON.stringify({
    document: {
      id: doc.id,
      filename: doc.original_filename,
      title: doc.title ?? null,
      language: doc.language ?? null,
      security_level: doc.security_level ?? null,
    },
    chunk_count: selected.length,
    chunks: selected.map((c) => ({
      id: c.id,
      index: c.chunk_index,
      page: c.page_number,
      section_path: c.section_path ?? [],
      chunk_type: c.chunk_type,
      element_id: c.element_id,
      token_count: c.token_count,
      char_count: c.char_count,
      keywords: c.keywords ?? [],
      embedding_model: c.embedding_model,
      embedded: c.embedded,
      search_excluded: c.disabled,
      edited: c.edited,
      has_parent_context: !!c.parent_chunk_text,
      // 표 청크면 출처 표와, 칸 안에서 떼어 낸 표의 바깥 표·칸(parent_table_id, parent_cell)
      ...(c.table ? { table: c.table } : {}),
      text: c.text,
    })),
  }, null, 2)
}
