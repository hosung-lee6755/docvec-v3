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

export interface StatusFilterOption {
  /** 문서 목록 API의 status 값. 이름이 같은 상태가 여럿이면 쉼표로 묶는다. */
  value: string
  label: string
}

// 문서 목록의 상태 거르기 선택지. 옛 고정 파이프라인의 REVIEW_PENDING과 워크플로우의 WAITING_REVIEW처럼
// 이름이 같은 상태는 한 선택지로 묶어, 목록에 "검토대기"가 두 번 나오지 않고 둘 다 함께 거른다.
export const STATUS_FILTER_OPTIONS: StatusFilterOption[] = Object.entries(STATUS_LABELS).reduce<StatusFilterOption[]>(
  (options, [status, label]) => {
    const same = options.find((o) => o.label === label)
    if (!same) return [...options, { value: status, label }]
    return options.map((o) => (o === same ? { ...o, value: `${o.value},${status}` } : o))
  },
  [],
)

/** 주소의 ?status= 값을 선택지 값으로 맞춘다. 묶인 상태 하나만 와도(예: WAITING_REVIEW) 그 묶음을 고른다. */
export function statusFilterValue(status: string): string {
  if (!status) return ''
  const option = STATUS_FILTER_OPTIONS.find((o) => o.value === status || o.value.split(',').includes(status))
  return option?.value ?? status
}
