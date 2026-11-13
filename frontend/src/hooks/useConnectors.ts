import { useEffect } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../lib/apiClient'
import type { SecurityLevel } from './useDocumentMetadata'

// v3 마일스톤 3 — 사내 파일 서버(SMB) 원천 연결 관리(관리자 전용).
// 비밀번호는 보내기만 하고 서버는 돌려주지 않는다. 판정과 동기화는 모두 백엔드가 한다.

export interface LevelRule {
  prefix: string
  level: SecurityLevel
}

export type ConnectorStatus = 'running' | 'success' | 'partial' | 'failed'

// smb=사내 파일 서버 공유 폴더, local=서버에 마운트한 폴더(파일 권한 없음)
export type ConnectorKind = 'smb' | 'local'
// file_acl=파일 서버 권한을 따름(사내 AD 필요), collection_only=컬렉션 권한만 적용
export type AclMode = 'file_acl' | 'collection_only'

export interface ConnectorOptions {
  directory_login: boolean
  local_root: string
  local_folders: string[]
}

export interface Connector {
  id: string
  name: string
  kind: ConnectorKind
  acl_mode: AclMode
  host: string
  port: number
  share: string
  base_path: string
  username: string
  service_account_sid: string | null
  collection_id: string
  collection_name: string | null
  level_rules: LevelRule[]
  sync_interval_minutes: number
  max_new_per_run: number
  enabled: boolean
  last_sync_at: string | null
  last_status: ConnectorStatus | null
  held_count: number
  error_count: number
  created_at: string
}

export interface ConnectorRun {
  id: string
  started_at: string
  finished_at: string | null
  status: ConnectorStatus
  counts: Record<string, number>
  error_message: string | null
  triggered_by: string | null
}

export interface ProblemItem {
  path: string
  state: 'held' | 'error'
  reason: string | null
  detail: Record<string, unknown> | null
  last_seen_at: string | null
}

export interface ConnectorDetail extends Connector {
  runs: ConnectorRun[]
  problem_items: ProblemItem[]
}

export interface ConnectorCreateInput {
  name: string
  kind?: ConnectorKind
  acl_mode?: AclMode
  host?: string
  port?: number
  share?: string
  base_path?: string
  username?: string
  password?: string
  service_account_sid?: string | null
  collection_id: string
  level_rules?: LevelRule[]
  sync_interval_minutes?: number
  max_new_per_run?: number
  enabled?: boolean
}

export interface ConnectorUpdateInput {
  name?: string
  password?: string
  level_rules?: LevelRule[]
  sync_interval_minutes?: number
  max_new_per_run?: number
  enabled?: boolean
  service_account_sid?: string | null
  acl_mode?: AclMode
}

export interface ConnectionTestResult {
  ok: boolean
  error: string | null
  sample: string[]
}

const KEY = ['connectors'] as const

export function useConnectorOptions() {
  return useQuery<ConnectorOptions>({
    queryKey: ['connectors', 'options'],
    queryFn: async () => (await apiClient.get('/admin/connectors/options')).data,
    staleTime: 60_000,
  })
}

export function useConnectors() {
  return useQuery<Connector[]>({
    queryKey: KEY,
    queryFn: async () => (await apiClient.get('/admin/connectors')).data,
  })
}

const POLL_MS = 5000

// pollUntil: 동기화를 요청한 뒤 작업이 실제로 시작될 때까지 기다리는 시각(ms). 그때까지는 실행 기록이 없을 수 있다.
export function useConnector(connectorId: string | null, pollUntil = 0) {
  const queryClient = useQueryClient()
  const query = useQuery<ConnectorDetail>({
    queryKey: ['connectors', connectorId],
    queryFn: async () => (await apiClient.get(`/admin/connectors/${connectorId}`)).data,
    enabled: !!connectorId,
    // 마지막 상태(last_status)는 실행이 끝나야 바뀌므로, 도는 중인지는 최근 실행 기록으로 판단한다
    refetchInterval: (query) => {
      const isRunning = query.state.data?.runs[0]?.status === 'running'
      return isRunning || Date.now() < pollUntil ? POLL_MS : false
    },
  })
  const lastSyncAt = query.data?.last_sync_at
  useEffect(() => {
    // 상세는 실행이 끝날 때까지 다시 읽지만 목록은 그대로다. 마지막 동기화 시각이 바뀌면 목록도 새로 읽는다
    if (lastSyncAt) queryClient.invalidateQueries({ queryKey: KEY, exact: true })
  }, [lastSyncAt, queryClient])
  return query
}

function useInvalidate() {
  const queryClient = useQueryClient()
  return () => queryClient.invalidateQueries({ queryKey: KEY })
}

export function useCreateConnector() {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: async (input: ConnectorCreateInput) => (await apiClient.post('/admin/connectors', input)).data as Connector,
    onSuccess: invalidate,
  })
}

export function useUpdateConnector() {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: async ({ id, input }: { id: string; input: ConnectorUpdateInput }) =>
      (await apiClient.patch(`/admin/connectors/${id}`, input)).data as Connector,
    onSuccess: invalidate,
  })
}

export function useDeleteConnector() {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: async (id: string) => { await apiClient.delete(`/admin/connectors/${id}`) },
    onSuccess: invalidate,
  })
}

export function useSyncConnector() {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: async (id: string) => (await apiClient.post(`/admin/connectors/${id}/sync`)).data,
    onSuccess: invalidate,
  })
}

export function useTestConnector() {
  return useMutation({
    mutationFn: async (id: string) =>
      (await apiClient.post(`/admin/connectors/${id}/test`)).data as ConnectionTestResult,
  })
}
