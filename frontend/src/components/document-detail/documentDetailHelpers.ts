import type { QualityMetrics } from '../../hooks/useDocumentRuns'

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
  normalization: '정규화', chunking: '청킹',
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
      return `사전 적용 ${metrics.dictionary_application_count ?? 0}건 · 항상 100점인 고정값(측정하지 않음, 사전 적용 건수는 참고용)`
    case 'chunking':
      return `생성된 청크 ${metrics.chunk_count ?? '-'}개`
    default:
      return ''
  }
}

export const RUN_TRIGGER_LABELS: Record<string, string> = {
  UPLOAD: '업로드', MANUAL: '수동 실행', REPROCESS: '부분 재처리', COLLECTION_REPROCESS: '컬렉션 재처리',
}

export const RUN_STATUS_BADGE: Record<string, string> = {
  QUEUED: 'bg-gray', RUNNING: 'bg-information', COMPLETED: 'bg-success',
  FAILED: 'bg-danger', CANCELLED: 'bg-gray', WAITING_REVIEW: 'bg-warning',
}

export const REVISION_SOURCE_LABELS: Record<string, string> = {
  PARSE: '자동 파싱',
  REVIEW_EDIT: '검토 단계 수정',
  RAG_EDIT: 'RAG 데이터 수정',
  RESTORE: '이력 복원',
}

export const QUALITY_WARNING_TAB: Record<string, TabKey> = {
  textExtraction: 'original', ocr: 'original', structure: 'structure',
  chunking: 'chunks', chunking_short: 'chunks', chunking_long: 'chunks',
}

export function toBlocksJson(text: string): string {
  const blocks = text.split('\n\n').filter((b) => b.trim().length > 0)
  return JSON.stringify({ blocks }, null, 2)
}
