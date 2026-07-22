// INGESTING/UPLOADING/REFINING/REVIEW_PENDING/CANCELLED come from the legacy
// fixed pipeline (still in use by /documents/{id}/proceed and edited_text
// reprocessing); VALIDATING/MASKING/WAITING_REVIEW come from the workflow
// engine (app/pipeline/tasks/workflow.py's _STATUS_FOR_BLOCK_TYPE + the
// quality_check review gate). Both can appear, so neither set is removed.
export const PROCESSING_STATUSES = [
  'QUEUED', 'INGESTING', 'PARSING', 'STRUCTURING',
  'NORMALIZING', 'CHUNKING', 'EMBEDDING', 'UPLOADING',
  'VALIDATING', 'MASKING', 'ANALYZING',
]

export const STATUS_BADGE_CLASSES: Record<string, string> = {
  QUEUED: 'bg-gray', INDEXED: 'bg-success', FAILED: 'bg-danger',
  INGESTING: 'bg-information', PARSING: 'bg-information', STRUCTURING: 'bg-information',
  NORMALIZING: 'bg-information', CHUNKING: 'bg-information', EMBEDDING: 'bg-information',
  UPLOADING: 'bg-information', REVIEW_PENDING: 'bg-warning', REFINING: 'bg-warning',
  CANCELLED: 'bg-gray',
  VALIDATING: 'bg-information', MASKING: 'bg-information', WAITING_REVIEW: 'bg-warning',
  ANALYZING: 'bg-information',
}

export const STATUS_LABELS: Record<string, string> = {
  QUEUED: '대기', INDEXED: '완료', FAILED: '실패',
  INGESTING: '처리중', PARSING: '파싱중', STRUCTURING: '구조화',
  NORMALIZING: '정규화', CHUNKING: '청킹', EMBEDDING: '임베딩',
  UPLOADING: '업로드', REVIEW_PENDING: '검토대기', REFINING: '정제중',
  CANCELLED: '취소',
  VALIDATING: '검증중', MASKING: '민감정보 처리중', WAITING_REVIEW: '검토대기',
  ANALYZING: '분석중',
}
