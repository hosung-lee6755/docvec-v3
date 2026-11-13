// 검토 대기와 실패 화면 전용 목록. 문서 목록과 달리 "왜 멈췄는지"를 함께 받는다.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../lib/apiClient'

// 배지(useWaitingReviewCount)와 같은 주기로 새로 받아, 처리가 끝나거나 새로 멈춘 문서를 반영한다
const QUEUE_REFRESH_MS = 15_000

export type ReviewReason = 'quality' | 'pii' | 'unknown'

export interface ReviewQueueItem {
  document_id: string
  filename: string
  collection_id: string | null
  collection_name: string | null
  run_id: string | null
  waiting_since: string | null
  reasons: ReviewReason[]
  quality_status: string | null
  overall_score: number | null
  warnings: string[]
  warning_categories: (string | null)[]
  pii_pending_count: number
  pii_entity_types: string[]
}

export interface ReviewQueueResponse {
  total: number
  counts: Record<ReviewReason, number>
  items: ReviewQueueItem[]
}

export interface FailureQueueItem {
  document_id: string
  filename: string
  collection_id: string | null
  collection_name: string | null
  run_id: string | null
  failed_block_type: string | null
  error_code: string | null
  error_message: string | null
  failed_at: string | null
  failure_count: number
  can_retry: boolean
}

export interface FailureQueueResponse {
  total: number
  items: FailureQueueItem[]
}

export function useReviewQueue() {
  return useQuery({
    queryKey: ['documents', 'review-queue'],
    queryFn: async () => (await apiClient.get<ReviewQueueResponse>('/documents/review-queue')).data,
    refetchInterval: QUEUE_REFRESH_MS,
  })
}

export function useFailureQueue() {
  return useQuery({
    queryKey: ['documents', 'failure-queue'],
    queryFn: async () => (await apiClient.get<FailureQueueResponse>('/documents/failure-queue')).data,
    refetchInterval: QUEUE_REFRESH_MS,
  })
}

/** 검토 게이트에서 멈춘 실행을 승인하고 이어서 처리한다. */
export function useApproveReview() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (runId: string) => (await apiClient.post(`/workflows/runs/${runId}/resume`)).data,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['documents'] }),
  })
}

/** 검토 게이트에서 멈춘 실행을 반려한다. 문서는 실패 상태가 되고 반려 사유가 남는다. */
export function useRejectReview() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (runId: string) => (await apiClient.post(`/workflows/runs/${runId}/cancel`)).data,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['documents'] }),
  })
}
