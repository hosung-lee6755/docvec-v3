import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../lib/apiClient'

export interface SearchHistoryItem {
  id: string
  query: string
  collection_id: string | null
  result_count: number
  search_mode: string
  created_at: string
}

export function useSearchHistory(limit = 10) {
  return useQuery<{ items: SearchHistoryItem[] }>({
    queryKey: ['search-history', limit],
    queryFn: async () => {
      const { data } = await apiClient.get('/search/history', { params: { limit } })
      return data
    },
  })
}
