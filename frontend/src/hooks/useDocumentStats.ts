import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../lib/apiClient'

/** /stats: 사용자에게 보이는 문서 전체의 상태별 건수. 대시보드와 문서 화면 요약 띠가 같이 쓴다. */
export interface DocumentStats {
  total_documents: number
  processing: number
  indexed: number
  waiting_review: number
  failed: number
  collections: number
}

export const DOCUMENT_STATS_QUERY_KEY = ['stats'] as const
const STATS_REFRESH_MS = 10000

export async function fetchDocumentStats(): Promise<DocumentStats> {
  const { data } = await apiClient.get<DocumentStats>('/stats')
  return data
}

/**
 * 문서 상태별 건수를 서버에서 센 값으로 받는다.
 *
 * 문서 화면 요약 띠가 지금 받은 한 페이지의 문서만 세어, 20건씩 보면 "처리 중 0", 100건씩 보면 "처리 중 1"처럼 표시 건수에
 * 따라 값이 달라지고 대시보드와도 달랐다(2026-11-26). 대시보드와 같은 질의 키를 써 두 화면이 같은 값을 보인다.
 */
export function useDocumentStats(refetchInterval: number | false = STATS_REFRESH_MS) {
  return useQuery({ queryKey: DOCUMENT_STATS_QUERY_KEY, queryFn: fetchDocumentStats, refetchInterval })
}
