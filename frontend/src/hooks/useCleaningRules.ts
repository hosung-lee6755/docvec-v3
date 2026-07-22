import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../lib/apiClient'

export type CleaningRuleType = 'REGEX_REPLACE' | 'EXACT_REMOVE' | 'LINE_FILTER'
export type CleaningRuleScope = 'DOCUMENT' | 'PARAGRAPH' | 'LINE'

export interface CleaningRule {
  id: string
  rule_name: string
  rule_type: CleaningRuleType | 'BUILTIN'
  pattern: string | null
  replacement: string | null
  scope: CleaningRuleScope
  priority: number
  enabled: boolean
  version: number
  created_by: string | null
  created_at: string
  updated_at: string
}

export interface CleaningRuleInput {
  rule_name: string
  rule_type: CleaningRuleType
  pattern: string
  replacement?: string | null
  scope?: CleaningRuleScope
  priority?: number
  enabled?: boolean
}

export function useCleaningRules() {
  return useQuery<{ items: CleaningRule[] }>({
    queryKey: ['cleaning-rules'],
    queryFn: async () => {
      const { data } = await apiClient.get('/admin/cleaning-rules')
      return data
    },
  })
}

export function useCreateCleaningRule() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (input: CleaningRuleInput) => {
      const { data } = await apiClient.post('/admin/cleaning-rules', input)
      return data as CleaningRule
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['cleaning-rules'] })
    },
  })
}

export function useUpdateCleaningRule() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, ...input }: { id: string } & Partial<CleaningRuleInput>) => {
      const { data } = await apiClient.patch(`/admin/cleaning-rules/${id}`, input)
      return data as CleaningRule
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['cleaning-rules'] })
    },
  })
}

export function useDeleteCleaningRule() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (ruleId: string) => {
      await apiClient.delete(`/admin/cleaning-rules/${ruleId}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['cleaning-rules'] })
    },
  })
}
