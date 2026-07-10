import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../lib/apiClient'

export interface ApiKeyStatus {
  provider: 'openai' | 'anthropic'
  registered: boolean
  updated_at: string | null
}

export function useApiKeys() {
  return useQuery<{ items: ApiKeyStatus[] }>({
    queryKey: ['api-keys'],
    queryFn: async () => {
      const { data } = await apiClient.get('/users/me/api-keys')
      return data
    },
  })
}

export function useSetApiKey() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ provider, apiKey }: { provider: string; apiKey: string }) => {
      const { data } = await apiClient.put(`/users/me/api-keys/${provider}`, { api_key: apiKey })
      return data as { message: string; provider: string }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['api-keys'] })
      queryClient.invalidateQueries({ queryKey: ['chat-models'] })
    },
  })
}

export function useDeleteApiKey() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (provider: string) => {
      await apiClient.delete(`/users/me/api-keys/${provider}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['api-keys'] })
      queryClient.invalidateQueries({ queryKey: ['chat-models'] })
    },
  })
}
