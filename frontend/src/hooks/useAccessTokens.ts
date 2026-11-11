import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../lib/apiClient'

// v3 마일스톤 4 — 외부 에이전트(MCP 클라이언트)에 넣는 개인 접근 토큰.
// 토큰 원문은 발급 응답에만 한 번 들어 있고, 서버는 다시 돌려주지 않는다.

export type TokenStatus = 'active' | 'expired' | 'revoked'

export interface AccessToken {
  id: string
  name: string
  token_prefix: string
  created_at: string
  expires_at: string
  last_used_at: string | null
  revoked_at: string | null
  status: TokenStatus
}

export interface AdminAccessToken extends AccessToken {
  user_id: string
  username: string
  email: string
}

export interface MyTokens {
  mcp_enabled: boolean
  mcp_path: string
  default_days: number
  max_days: number
  items: AccessToken[]
}

export interface IssuedToken extends AccessToken {
  token: string
}

const MY_KEY = ['access-tokens', 'me'] as const
const ALL_KEY = ['access-tokens', 'all'] as const

export function useMyAccessTokens() {
  return useQuery<MyTokens>({
    queryKey: MY_KEY,
    queryFn: async () => (await apiClient.get('/users/me/access-tokens')).data,
  })
}

export function useAllAccessTokens(enabled = true) {
  return useQuery<{ mcp_enabled: boolean; items: AdminAccessToken[] }>({
    queryKey: ALL_KEY,
    queryFn: async () => (await apiClient.get('/admin/access-tokens')).data,
    enabled,
  })
}

function useInvalidateTokens() {
  const queryClient = useQueryClient()
  return () => queryClient.invalidateQueries({ queryKey: ['access-tokens'] })
}

export function useCreateAccessToken() {
  const invalidate = useInvalidateTokens()
  return useMutation({
    mutationFn: async (input: { name: string; expires_in_days: number }) =>
      (await apiClient.post('/users/me/access-tokens', input)).data as IssuedToken,
    onSuccess: invalidate,
  })
}

export function useRevokeMyAccessToken() {
  const invalidate = useInvalidateTokens()
  return useMutation({
    mutationFn: async (id: string) => { await apiClient.delete(`/users/me/access-tokens/${id}`) },
    onSuccess: invalidate,
  })
}

export function useRevokeAnyAccessToken() {
  const invalidate = useInvalidateTokens()
  return useMutation({
    mutationFn: async (id: string) => { await apiClient.delete(`/admin/access-tokens/${id}`) },
    onSuccess: invalidate,
  })
}

export const TOKEN_STATUS_LABELS: Record<TokenStatus, string> = {
  active: '사용 중',
  expired: '만료됨',
  revoked: '회수됨',
}

export const TOKEN_STATUS_BADGE: Record<TokenStatus, string> = {
  active: 'bg-success',
  expired: 'bg-gray',
  revoked: 'bg-danger',
}

// Claude Code에 붙이는 명령. 주소는 지금 보고 있는 웹 주소를 그대로 쓴다.
export function mcpConnectCommand(origin: string, path: string, token: string): string {
  return `claude mcp add --transport http docvec ${origin}${path} --header "Authorization: Bearer ${token}"`
}
