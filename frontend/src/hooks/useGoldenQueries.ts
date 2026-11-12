import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../lib/apiClient'

export interface GoldenQuery {
  id: string
  collection_id: string
  query: string
  expected_document_ids: string[]
  created_at: string
}

export type GoldenRunStatus = 'QUEUED' | 'RUNNING' | 'DONE' | 'FAILED'
export type GoldenRunTrigger =
  | 'manual'
  | 'search_settings'
  | 'dictionary'
  | 'new_version'
  | 'lifecycle'
  | 'document_deleted'

export type GoldenRegressedMetric = 'mean_hit_rate' | 'mean_recall' | 'mean_mrr'

export interface GoldenRegressionMetric {
  baseline: number | null
  current: number | null
  delta: number | null
}

export interface GoldenRegression {
  baseline_run_id: string
  tolerance: number
  metrics: Partial<Record<GoldenRegressedMetric, GoldenRegressionMetric>>
  regressed_metrics: GoldenRegressedMetric[]
  lost_queries: { golden_query_id: string; query: string }[]
}

export interface GoldenEvalQueryResult {
  golden_query_id: string
  query: string
  expected_document_ids: string[]
  retrieved_document_ids: string[]
  precision: number | null
  recall: number | null
  hit?: boolean | null
  reciprocal_rank?: number | null
  first_hit_rank?: number | null
  // 요청자가 볼 수 없는 기대 문서가 있어 질의별 점수를 가렸다
  masked?: boolean
}

export interface GoldenEvalRun {
  id: string
  collection_id: string
  top_k: number
  status: GoldenRunStatus
  trigger: GoldenRunTrigger
  mean_precision: number | null
  mean_recall: number | null
  mean_hit_rate: number | null
  mean_mrr: number | null
  is_baseline: boolean
  is_regression: boolean | null
  regression: GoldenRegression | null
  search_settings: Record<string, unknown> | null
  error_message: string | null
  results: GoldenEvalQueryResult[] | null
  created_at: string
  completed_at: string | null
}

export const GOLDEN_RUN_POLL_INTERVAL_MS = 3000

export function isGoldenRunActive(run: Pick<GoldenEvalRun, 'status'>): boolean {
  return run.status === 'QUEUED' || run.status === 'RUNNING'
}

export function useGoldenQueries(collectionId: string | null) {
  return useQuery<{ items: GoldenQuery[] }>({
    queryKey: ['golden-queries', collectionId],
    queryFn: async () => {
      const { data } = await apiClient.get(`/collections/${collectionId}/golden-queries`)
      return data
    },
    enabled: !!collectionId,
  })
}

export function useCreateGoldenQuery(collectionId: string | null) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (input: { query: string; expected_document_ids: string[] }) => {
      const { data } = await apiClient.post(`/collections/${collectionId}/golden-queries`, input)
      return data as GoldenQuery
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['golden-queries', collectionId] })
    },
  })
}

export function useUpdateGoldenQuery(collectionId: string | null) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ queryId, ...input }: { queryId: string; query?: string; expected_document_ids?: string[] }) => {
      const { data } = await apiClient.patch(`/collections/${collectionId}/golden-queries/${queryId}`, input)
      return data as GoldenQuery
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['golden-queries', collectionId] })
    },
  })
}

export function useDeleteGoldenQuery(collectionId: string | null) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (queryId: string) => {
      await apiClient.delete(`/collections/${collectionId}/golden-queries/${queryId}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['golden-queries', collectionId] })
    },
  })
}

// 실행 중인 평가가 있으면 3초마다 다시 가져와 상태를 갱신한다. 모두 끝나면 멈춘다.
export function useGoldenEvalRuns(collectionId: string | null) {
  return useQuery<{ items: GoldenEvalRun[] }>({
    queryKey: ['golden-eval-runs', collectionId],
    queryFn: async () => {
      const { data } = await apiClient.get(`/collections/${collectionId}/golden-eval-runs`)
      return data
    },
    enabled: !!collectionId,
    refetchInterval: (query) => {
      const items = query.state.data?.items ?? []
      return items.some(isGoldenRunActive) ? GOLDEN_RUN_POLL_INTERVAL_MS : false
    },
  })
}

// topK가 null이면 컬렉션의 검색 설정 top-k를 따른다.
export function useRunGoldenEval(collectionId: string | null) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (topK: number | null) => {
      const { data } = await apiClient.post(`/collections/${collectionId}/golden-eval-runs`, { top_k: topK })
      return data as GoldenEvalRun
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['golden-eval-runs', collectionId] })
    },
  })
}

export function useSetGoldenBaseline(collectionId: string | null) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (runId: string) => {
      const { data } = await apiClient.post(`/collections/${collectionId}/golden-eval-runs/${runId}/baseline`)
      return data as GoldenEvalRun
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['golden-eval-runs', collectionId] })
    },
  })
}
