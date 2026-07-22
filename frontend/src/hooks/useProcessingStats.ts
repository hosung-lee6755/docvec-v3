import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../lib/apiClient'

export interface BlockStat {
  block_type: string
  execution_count: number
  failure_rate: number
  avg_duration_seconds: number | null
}

export interface RecentFailure {
  document_id: string
  filename: string
  error_message: string | null
  created_at: string
}

export interface ProcessingStats {
  processed_documents: number
  avg_quality: number | null
  failure_rate: number
  reprocess_rate: number
  waiting_review_count: number
  avg_queue_seconds: number | null
  block_stats: BlockStat[]
  recent_failures: RecentFailure[]
}

export function useProcessingStats() {
  return useQuery<ProcessingStats>({
    queryKey: ['stats', 'processing'],
    queryFn: async () => {
      const { data } = await apiClient.get('/stats/processing')
      return data
    },
    staleTime: 30 * 1000,
  })
}
