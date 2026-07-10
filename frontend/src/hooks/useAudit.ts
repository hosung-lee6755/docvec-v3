import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../lib/apiClient'

export interface AuditLogItem {
  id: string
  user_id: string | null
  action: string
  resource_type: string | null
  resource_id: string | null
  detail: Record<string, unknown> | null
  ip_address: string | null
  created_at: string
}

interface AuditLogListResponse {
  total: number
  items: AuditLogItem[]
}

export interface AuditLogFilters {
  action?: string
  limit?: number
  offset?: number
}

export function useAuditLogs(filters: AuditLogFilters) {
  return useQuery<AuditLogListResponse>({
    queryKey: ['audit-logs', filters],
    queryFn: async () => {
      const { data } = await apiClient.get('/admin/audit-logs', { params: filters })
      return data
    },
  })
}
