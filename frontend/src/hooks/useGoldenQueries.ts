import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../lib/apiClient'

export interface GoldenQuery {
  id: string
  collection_id: string
  query: string
  expected_document_ids: string[]
  created_at: string
}

export interface GoldenEvalQueryResult {
  golden_query_id: string
  query: string
  expected_document_ids: string[]
  retrieved_document_ids: string[]
  precision: number
  recall: number
}

export interface GoldenEvalRun {
  id: string
  collection_id: string
  top_k: number
  mean_precision: number
  mean_recall: number
  results: GoldenEvalQueryResult[]
  created_at: string
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

export function useGoldenEvalRuns(collectionId: string | null) {
  return useQuery<{ items: GoldenEvalRun[] }>({
    queryKey: ['golden-eval-runs', collectionId],
    queryFn: async () => {
      const { data } = await apiClient.get(`/collections/${collectionId}/golden-eval-runs`)
      return data
    },
    enabled: !!collectionId,
  })
}

export function useRunGoldenEval(collectionId: string | null) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (topK: number) => {
      const { data } = await apiClient.post(`/collections/${collectionId}/golden-eval-runs`, { top_k: topK })
      return data as GoldenEvalRun
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['golden-eval-runs', collectionId] })
    },
  })
}
