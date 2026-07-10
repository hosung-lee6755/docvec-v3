import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../lib/apiClient'

interface UsageSummary {
  total_requests: number
  total_input_tokens: number
  total_output_tokens: number
  total_cost_usd: number
}

interface UsageByModel {
  provider: string
  model_key: string
  requests: number
  input_tokens: number
  output_tokens: number
  cost_usd: number
}

interface UsageByUser {
  user_id: string
  username: string
  requests: number
  input_tokens: number
  output_tokens: number
  cost_usd: number
}

interface UsageResponse {
  summary: UsageSummary
  by_model: UsageByModel[]
  by_user: UsageByUser[]
}

export function useUsageSummary() {
  return useQuery<UsageResponse>({
    queryKey: ['usage-summary'],
    queryFn: async () => {
      const { data } = await apiClient.get('/admin/usage')
      return data
    },
  })
}
