export const PROCESSING_STATUSES = [
  'QUEUED', 'INGESTING', 'PARSING', 'STRUCTURING',
  'NORMALIZING', 'CHUNKING', 'EMBEDDING', 'UPLOADING',
]

export const STATUS_BADGE_CLASSES: Record<string, string> = {
  QUEUED: 'bg-gray', INDEXED: 'bg-success', FAILED: 'bg-danger',
  INGESTING: 'bg-information', PARSING: 'bg-information', STRUCTURING: 'bg-information',
  NORMALIZING: 'bg-information', CHUNKING: 'bg-information', EMBEDDING: 'bg-information',
  UPLOADING: 'bg-information', REVIEW_PENDING: 'bg-warning', REFINING: 'bg-warning',
  CANCELLED: 'bg-gray',
}

export const STATUS_LABELS: Record<string, string> = {
  QUEUED: '대기', INDEXED: '완료', FAILED: '실패',
  INGESTING: '처리중', PARSING: '파싱중', STRUCTURING: '구조화',
  NORMALIZING: '정규화', CHUNKING: '청킹', EMBEDDING: '임베딩',
  UPLOADING: '업로드', REVIEW_PENDING: '검토대기', REFINING: '정제중',
  CANCELLED: '취소',
}
