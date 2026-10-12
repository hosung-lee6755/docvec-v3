import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../lib/apiClient'
import type { Document } from './useDocuments'

export interface DocumentRunItem {
  id: string
  trigger: 'UPLOAD' | 'MANUAL' | 'REPROCESS' | 'COLLECTION_REPROCESS'
  status: 'QUEUED' | 'RUNNING' | 'COMPLETED' | 'FAILED' | 'CANCELLED' | 'WAITING_REVIEW'
  started_at: string | null
  completed_at: string | null
  dictionary_version: number | null
  parent_run_id: string | null
  started_block_id: string | null
  impact: ReprocessImpact | null
}

export interface DocumentRunsResult {
  document_id: string
  runs: DocumentRunItem[]
}

export function useDocumentRuns(documentId: string, enabled = true) {
  return useQuery<DocumentRunsResult>({
    queryKey: ['documents', documentId, 'runs'],
    queryFn: async () => {
      const { data } = await apiClient.get(`/documents/${documentId}/runs`)
      return data
    },
    enabled: enabled && !!documentId,
    refetchInterval: (query) => {
      const runs = query.state.data?.runs ?? []
      const isActive = runs.some((r) => r.status === 'QUEUED' || r.status === 'RUNNING')
      return isActive ? 3000 : false
    },
  })
}

export interface QualityMetrics {
  overall_score?: number
  text_chars?: number
  broken_char_ratio?: number
  empty_page_ratio?: number
  node_count?: number
  dictionary_application_count?: number
  chunk_count?: number
  // quality_blocks.py의 "너무 짧은/큰 청크" 경고가 가리키는 정확한 DocumentChunk.id
  // 목록 — 경고 클릭 시 청크 탭으로 이동만 하는 게 아니라 해당 청크로 바로
  // 스크롤할 수 있게 한다.
  short_chunk_ids?: string[]
  long_chunk_ids?: string[]
  textExtraction?: number
  ocr?: number
  structure?: number
  normalization?: number
  chunking?: number
}

export interface QualityReport {
  id: string
  run_id: string
  overall_score: number | null
  scores: Record<string, number> | null
  metrics: QualityMetrics | null
  warnings: string[] | null
  warning_categories: string[] | null
  status: 'SUCCESS' | 'SUCCESS_WITH_WARNING' | 'REVIEW_REQUIRED' | 'PARTIAL_FAILURE' | 'FAILURE'
  reviewed_by: string | null
  reviewed_at: string | null
  review_note: string | null
  created_at: string
}

export function useDocumentQuality(documentId: string, enabled = true) {
  return useQuery<QualityReport | null>({
    queryKey: ['documents', documentId, 'quality'],
    queryFn: async () => {
      const { data } = await apiClient.get(`/documents/${documentId}/quality`)
      return data
    },
    enabled: enabled && !!documentId,
  })
}

export interface ReprocessImpact {
  reason: string | null
  changeType: string
  affectedBlocks: string[]
  affectedNodeCount: number
  affectedChunkCount: number
  fullReprocessingRequired: boolean
}

export function useReprocessImpact(
  documentId: string,
  startBlockType: string | null,
  startBlockInstanceId: string | null,
) {
  return useQuery<ReprocessImpact>({
    queryKey: ['documents', documentId, 'reprocess-impact', startBlockType, startBlockInstanceId],
    queryFn: async () => {
      const { data } = await apiClient.get(`/documents/${documentId}/reprocess/impact`, {
        params: {
          start_block_type: startBlockType ?? undefined,
          start_block_instance_id: startBlockInstanceId ?? undefined,
        },
      })
      return data
    },
    enabled: !!documentId && (!!startBlockType || !!startBlockInstanceId),
  })
}

export function useStartPartialReprocess() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({
      documentId, startBlockType, startBlockInstanceId, reason, timeoutOverrides, useLatestVersion,
    }: {
      documentId: string
      startBlockType?: string
      startBlockInstanceId?: string
      reason?: string
      // {block_type: timeoutSeconds} — 이 재처리 run에만 적용되는 시간 제한 오버라이드.
      timeoutOverrides?: Record<string, number>
      // true면 이전 실행의 워크플로우 버전이 아니라 최신 게시 버전으로 처음부터 처리한다.
      useLatestVersion?: boolean
    }) => {
      const { data } = await apiClient.post(`/documents/${documentId}/reprocess`, {
        start_block_type: startBlockType ?? null,
        start_block_instance_id: startBlockInstanceId ?? null,
        reason: reason ?? null,
        timeout_overrides: timeoutOverrides ?? null,
        use_latest_version: useLatestVersion ?? false,
      })
      return data as { message: string; run_id: string; status: string; impact: ReprocessImpact }
    },
    onSuccess: (_data, { documentId }) => {
      queryClient.setQueryData<Document>(['documents', documentId], (old) =>
        old ? { ...old, status: 'CHUNKING' } : old
      )
      queryClient.invalidateQueries({ queryKey: ['documents', documentId, 'runs'] })
      queryClient.invalidateQueries({ queryKey: ['documents', documentId, 'quality'] })
    },
  })
}
