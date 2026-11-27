import type { DocumentLifecycleFilter, DocumentQualityFilter, DocumentSortBy, SortOrder } from '../hooks/useDocuments'

// 문서 목록의 쪽·표시 건수·정렬·검색어·품질·버전 거르기를 주소에 담는다(2026-11-27).
// 예전에는 화면 상태로만 들고 있어, 문서 상세에서 뒤로 오면 1쪽·기본 정렬로 돌아가 보던 자리를 다시 찾아야 했다.
// 기본값은 주소에 적지 않는다.

export const PAGE_SIZE_OPTIONS = [10, 20, 50, 100, 200] as const
const DEFAULT_LIMIT = 20
const SORT_KEYS: readonly DocumentSortBy[] = ['created_at', 'filename', 'file_size', 'status']
const QUALITY_KEYS: readonly DocumentQualityFilter[] = ['low_ocr', 'warning', 'failure']
const LIFECYCLE_KEYS: readonly DocumentLifecycleFilter[] = ['current', 'archived', 'superseded', 'all']

export interface DocumentListView {
  page: number
  limit: number
  sortBy: DocumentSortBy
  order: SortOrder
  filename: string
  quality: DocumentQualityFilter | ''
  lifecycle: DocumentLifecycleFilter | ''
}

function pick<T extends string>(value: string | null, allowed: readonly T[]): T | '' {
  return value !== null && (allowed as readonly string[]).includes(value) ? (value as T) : ''
}

function positiveInt(value: string | null): number | null {
  const n = Number(value)
  return value !== null && Number.isInteger(n) && n > 0 ? n : null
}

export function readDocumentListView(params: URLSearchParams): DocumentListView {
  const limit = positiveInt(params.get('limit'))
  return {
    page: positiveInt(params.get('page')) ?? 1,
    limit: limit !== null && (PAGE_SIZE_OPTIONS as readonly number[]).includes(limit) ? limit : DEFAULT_LIMIT,
    sortBy: pick(params.get('sort'), SORT_KEYS) || 'created_at',
    order: params.get('order') === 'asc' ? 'asc' : 'desc',
    filename: params.get('q') ?? '',
    quality: pick(params.get('quality'), QUALITY_KEYS),
    lifecycle: pick(params.get('lifecycle'), LIFECYCLE_KEYS),
  }
}

export type DocumentListChange = Partial<Omit<DocumentListView, 'page'>>

const PARAM_OF: Record<keyof DocumentListChange, string> = {
  limit: 'limit', sortBy: 'sort', order: 'order', filename: 'q', quality: 'quality', lifecycle: 'lifecycle',
}

function isDefault(key: keyof DocumentListChange, value: string | number): boolean {
  if (key === 'limit') return value === DEFAULT_LIMIT
  if (key === 'sortBy') return value === 'created_at'
  if (key === 'order') return value === 'desc'
  return value === ''
}

/** 보기를 바꾼 주소. 거르기·정렬·표시 건수를 바꾸면 결과 범위가 달라지므로 1쪽으로 간다. */
export function withDocumentListChange(params: URLSearchParams, change: DocumentListChange): URLSearchParams {
  const next = new URLSearchParams(params)
  for (const [key, value] of Object.entries(change) as [keyof DocumentListChange, string | number][]) {
    if (isDefault(key, value)) next.delete(PARAM_OF[key])
    else next.set(PARAM_OF[key], String(value))
  }
  next.delete('page')
  return next
}

export function withDocumentListPage(params: URLSearchParams, page: number): URLSearchParams {
  const next = new URLSearchParams(params)
  if (page > 1) next.set('page', String(page))
  else next.delete('page')
  return next
}
