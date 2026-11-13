import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import axios from 'axios'
import { apiClient } from '../lib/apiClient'
import type { SecurityLevel } from './useDocumentMetadata'
import type { User } from './useUsers'

/** 로그인 화면이 인증 없이 읽는 가입 정책 */
export interface AuthOptions {
  self_signup_enabled: boolean
  admin_code_signup: boolean
  directory_login: boolean
}

export type AccountRole = 'viewer' | 'editor' | 'admin'

export interface AccountCreatePayload {
  email: string
  username: string
  role: AccountRole
  clearance_level?: SecurityLevel
}

export interface IssuedAccount {
  user: User
  temporary_password: string
}

export interface ImportedAccount {
  email: string
  username: string
  role: string
  groups: string[]
  temporary_password: string
}

export interface ImportResult {
  created: ImportedAccount[]
  count: number
}

export interface ImportProblem {
  line: number
  message: string
}

export function useAuthOptions() {
  return useQuery<AuthOptions>({
    queryKey: ['auth-options'],
    queryFn: async () => {
      const { data } = await axios.get('/api/v1/auth/options')
      return data
    },
    staleTime: 60_000,
  })
}

export function useCreateAccount() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (payload: AccountCreatePayload) => {
      const { data } = await apiClient.post('/users', payload)
      return data as IssuedAccount
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
    },
  })
}

export function useResetPassword() {
  return useMutation({
    mutationFn: async (userId: string) => {
      const { data } = await apiClient.post(`/users/${userId}/reset-password`)
      return data as { temporary_password: string }
    },
  })
}

export function useImportAccounts() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (file: File) => {
      const form = new FormData()
      form.append('file', file)
      const { data } = await apiClient.post('/users/import', form)
      return data as ImportResult
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
      queryClient.invalidateQueries({ queryKey: ['groups'] })
    },
  })
}

/** 일괄 등록이 거절됐을 때 서버가 돌려준 줄별 문제. 다른 오류면 빈 배열이다. */
export function importProblems(error: unknown): ImportProblem[] {
  if (!axios.isAxiosError(error)) return []
  const detail = error.response?.data?.detail
  if (detail && typeof detail === 'object' && Array.isArray(detail.problems)) return detail.problems
  return []
}

/** 같은 이메일의 AD 사용자가 처음 로그인하거나 다음 동기화 때 이 로컬 계정을 이어받게 한다 */
export function useLinkDirectory() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (userId: string) => {
      const { data } = await apiClient.post(`/users/${userId}/link-directory`)
      return data as User
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
    },
  })
}

/** 주기를 기다리지 않고 AD와 지금 맞춘다(백그라운드 작업) */
export function useSyncDirectory() {
  return useMutation({
    mutationFn: async () => {
      const { data } = await apiClient.post('/users/directory-sync')
      return data as { status: string }
    },
  })
}
