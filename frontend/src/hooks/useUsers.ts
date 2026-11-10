import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../lib/apiClient'
import type { SecurityLevel } from './useDocumentMetadata'

export interface User {
  id: string
  email: string
  username: string
  role: string
  is_active: boolean
  // v3 데이터 열람등급 — 시스템 역할(role)과 별개
  clearance_level: SecurityLevel
  created_at: string
}

interface UserListResponse {
  items: User[]
}

interface UpdateUserPayload {
  role?: 'viewer' | 'editor' | 'admin'
  is_active?: boolean
  clearance_level?: SecurityLevel
}

export function useUsers() {
  return useQuery<UserListResponse>({
    queryKey: ['users'],
    queryFn: async () => {
      const { data } = await apiClient.get('/users')
      return data
    },
  })
}

export function useUpdateUser() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, payload }: { id: string; payload: UpdateUserPayload }) => {
      const { data } = await apiClient.patch(`/users/${id}`, payload)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
    },
  })
}

export function useDeleteUser() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) => {
      await apiClient.delete(`/users/${id}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
    },
  })
}
