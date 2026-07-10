import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../lib/apiClient'

export interface ProcessingJobItem {
  id: string
  job_type: string
  status: string
  started_at: string | null
  completed_at: string | null
  result_summary: string | null
  error_message: string | null
}

export function useProcessingJobs(documentId: string, isProcessing: boolean) {
  return useQuery<{ items: ProcessingJobItem[] }>({
    queryKey: ['documents', documentId, 'jobs'],
    queryFn: async () => {
      const { data } = await apiClient.get(`/documents/${documentId}/jobs`)
      return data
    },
    enabled: !!documentId,
    // Keep polling until every job is settled, not just while the document's own status
    // says "processing" — the document can flip to a terminal status (e.g. INDEXED) one
    // poll tick before the last job (EMBED/UPLOAD) is marked COMPLETED, which otherwise
    // freezes the step list on a stale "running" snapshot forever.
    refetchInterval: (query) => {
      const items = query.state.data?.items
      const hasUnsettledJob = items?.some((job) => job.status !== 'COMPLETED' && job.status !== 'FAILED')
      return isProcessing || hasUnsettledJob ? 2000 : false
    },
  })
}
