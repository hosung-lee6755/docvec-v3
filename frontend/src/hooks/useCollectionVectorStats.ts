import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../lib/apiClient'

interface CollectionVectorStats {
  embedding_model: string
  embedding_model_label: string
  dimension: number | null
  total_documents: number
  indexed_documents: number
  total_vectors: number
  reembed_status: 'PENDING' | 'RUNNING' | 'COMPLETED' | 'FAILED' | null
  reembed_progress: string | null
}

export function useCollectionVectorStats(collectionId: string | null) {
  return useQuery<CollectionVectorStats>({
    queryKey: ['collection-vector-stats', collectionId],
    queryFn: async () => {
      const { data } = await apiClient.get(`/collections/${collectionId}/vector-stats`)
      return data
    },
    enabled: !!collectionId,
  })
}
