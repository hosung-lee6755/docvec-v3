import { useMutation, useQuery } from '@tanstack/react-query'
import { apiClient } from '../lib/apiClient'

export type Grounding = 'passed' | 'failed' | 'skipped'
export type SourceAccess = 'visible' | 'hidden' | 'deleted'

export interface AnswerTraceItem {
  id: string
  created_at: string
  user_id: string | null
  username: string | null
  query: string
  status: 'DONE' | 'FAILED'
  grounding: Grounding | null
  broadened: boolean
  cache_hit: boolean
  model_key: string | null
  source_count: number
  cited_count: number
}

export interface AnswerTraceSource {
  rank: number
  document_id: string | null
  collection_id: string | null
  filename: string | null
  security_level: string | null
  page_number: number | null
  source_kind: 'chunk' | 'table' | 'summary' | 'cached'
  chunk_ref: string | null
  score: number | null
  cited: boolean
  access: SourceAccess
  text: string | null
  text_changed: boolean | null
}

export interface AnswerTraceDetail {
  id: string
  created_at: string
  username: string | null
  user_role: string | null
  clearance_level: string | null
  group_ids: string[]
  accessible_collection_count: number
  access_fingerprint: string | null
  scope_collection_id: string | null
  scope_project_id: string | null
  intent: string | null
  broadened: boolean
  grounding: Grounding | null
  cache_hit: boolean
  model_key: string | null
  provider: string | null
  verifier_model: string | null
  system_prompt_source: string | null
  input_tokens: number | null
  output_tokens: number | null
  latency_ms: number | null
  query: string
  answer: string | null
  status: 'DONE' | 'FAILED'
  error_message: string | null
  sources: AnswerTraceSource[]
}

export interface AnswerTraceFilters {
  document_id?: string
  grounding?: Grounding
  from_date?: string
  to_date?: string
  limit?: number
  offset?: number
}

export function useAnswerTraces(filters: AnswerTraceFilters) {
  return useQuery<{ total: number; items: AnswerTraceItem[] }>({
    queryKey: ['answer-traces', filters],
    queryFn: async () => {
      const { data } = await apiClient.get('/admin/answer-traces', { params: filters })
      return data
    },
  })
}

export function useAnswerTrace(traceId: string | null) {
  return useQuery<AnswerTraceDetail>({
    queryKey: ['answer-trace', traceId],
    queryFn: async () => {
      const { data } = await apiClient.get(`/admin/answer-traces/${traceId}`)
      return data
    },
    enabled: !!traceId,
  })
}

export function useDownloadGovernanceReport() {
  return useMutation({
    mutationFn: async (period: { from_date: string; to_date: string }) => {
      const response = await apiClient.get('/admin/governance/report', {
        params: period,
        responseType: 'blob',
      })
      const url = URL.createObjectURL(response.data as Blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `ai-governance-report-${period.from_date.slice(0, 10)}-${period.to_date.slice(0, 10)}.docx`
      link.click()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    },
  })
}
