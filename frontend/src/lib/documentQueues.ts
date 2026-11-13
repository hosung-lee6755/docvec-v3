// 검토 대기와 실패 화면이 함께 쓰는 표기와 계산.
import { explainFailure } from './apiError'
import type { FailureQueueItem, ReviewReason } from '../hooks/useDocumentQueues'

export const REVIEW_REASON_LABELS: Record<ReviewReason, string> = {
  quality: '품질 경고',
  pii: '개인정보 승인 대기',
  unknown: '사유 미기록',
}

// 품질 보고서의 warning_categories → 화면 이름
export const QUALITY_CATEGORY_LABELS: Record<string, string> = {
  textExtraction: '텍스트 추출',
  ocr: 'OCR',
  structure: '구조',
  normalization: '정제',
  chunking: '청크',
}

export const QUALITY_STATUS_LABELS: Record<string, string> = {
  FAILURE: '품질 실패',
  PARTIAL_FAILURE: '일부 실패',
  REVIEW_REQUIRED: '검토 필요',
  SUCCESS_WITH_WARNING: '경고 있음',
  SUCCESS: '정상',
}

export const PII_TYPE_LABELS: Record<string, string> = {
  RRN: '주민등록번호',
  PHONE: '전화번호',
  EMAIL: '이메일',
  ACCOUNT: '계좌번호',
  CARD: '카드번호',
  NAME: '이름',
}

const MINUTE = 60_000
const HOUR = 60 * MINUTE
const DAY = 24 * HOUR

/** "3분 전", "5시간 전", "2일 전". 미래 시각이나 잘못된 값은 "방금"으로 본다. */
export function formatElapsed(iso: string | null, now: number = Date.now()): string {
  if (!iso) return '-'
  const elapsed = now - new Date(iso).getTime()
  if (!Number.isFinite(elapsed) || elapsed < MINUTE) return '방금'
  if (elapsed < HOUR) return `${Math.floor(elapsed / MINUTE)}분 전`
  if (elapsed < DAY) return `${Math.floor(elapsed / HOUR)}시간 전`
  return `${Math.floor(elapsed / DAY)}일 전`
}

/** 하루 넘게 기다린 검토는 눈에 띄게 한다 */
export function isStale(iso: string | null, now: number = Date.now()): boolean {
  return !!iso && now - new Date(iso).getTime() >= DAY
}

export interface FailureCauseGroup {
  cause: string
  count: number
}

/** 실패 원인 문장의 첫 문장으로 묶어, 많은 원인부터 돌려준다. 같은 원인을 한 번에 처리하기 쉽게 한다. */
export function groupFailureCauses(items: readonly FailureQueueItem[]): FailureCauseGroup[] {
  const counts = new Map<string, number>()
  for (const item of items) {
    const cause = failureCauseHeadline(item.error_message)
    counts.set(cause, (counts.get(cause) ?? 0) + 1)
  }
  return [...counts.entries()]
    .map(([cause, count]) => ({ cause, count }))
    .sort((a, b) => b.count - a.count || a.cause.localeCompare(b.cause, 'ko'))
}

/** 원인 설명의 첫 문장(마침표까지). 원문을 괄호에 붙인 긴 설명도 묶을 수 있게 한다. */
export function failureCauseHeadline(message: string | null): string {
  const explained = explainFailure(message)
  const end = explained.indexOf('. ')
  return end === -1 ? explained : explained.slice(0, end + 1)
}
