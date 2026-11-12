import type { DocumentLifecycleFilter, DocumentLifecycleState } from '../hooks/useDocuments'

export const LIFECYCLE_STATE_LABELS: Record<DocumentLifecycleState, string> = {
  pending: '처리 중',
  current: '현재 버전',
  superseded: '이전 버전',
  archived: '보관됨',
}

export const LIFECYCLE_FILTER_LABELS: Record<DocumentLifecycleFilter, string> = {
  current: '현재 버전만',
  archived: '보관된 문서',
  superseded: '이전 버전',
  all: '모든 버전',
}

// 만료일을 로컬 시간 기준 YYYY-MM-DD로 바꾼다. 날짜 입력 칸과 배지에 같이 쓴다.
export function formatLocalDate(iso: string): string {
  const date = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

// 날짜 입력값(YYYY-MM-DD)의 그날 끝(로컬 23:59:59.999)을 ISO 문자열로 바꾼다.
export function endOfLocalDayIso(dateValue: string): string {
  return new Date(`${dateValue}T23:59:59.999`).toISOString()
}
