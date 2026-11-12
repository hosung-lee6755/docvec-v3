import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../lib/apiClient'
import type { Document, DocumentLifecycleState } from './useDocuments'

export interface DocumentVersion {
  id: string
  version_number: number
  lifecycle_state: DocumentLifecycleState
  status: string
  filename: string
  file_size: number
  created_at: string
  created_by: string | null
  expires_at: string | null
  archived_at: string | null
  // 지금 검색 답변에 쓰일 수 있는 버전인지(INDEXED이고 current이며 만료되지 않음)
  is_retrievable: boolean
}

export interface DocumentVersionsResult {
  lineage_id: string
  items: DocumentVersion[]
}

export interface VersionCompareResult {
  base_id: string
  base_version: number
  target_id: string
  target_version: number
  added_lines: number
  removed_lines: number
  // unified diff 줄. '+', '-', ' ', '@@', '---', '+++'로 시작한다.
  diff: string[]
  truncated: boolean
}

// 버전 이력은 문서 상세 키 아래(['documents', id, 'versions'])에 둔다.
// 수명주기 변경 뒤에는 ['documents'] 전체를 무효화하므로 여기도 함께 갱신된다.
export function useDocumentVersions(id: string) {
  return useQuery<DocumentVersionsResult>({
    queryKey: ['documents', id, 'versions'],
    queryFn: async () => {
      const { data } = await apiClient.get(`/documents/${id}/versions`)
      return data
    },
    enabled: !!id,
  })
}

// otherId가 없으면 비교하지 않는다. 서버가 버전 번호 순으로 정렬하므로 순서는 상관없다.
export function useCompareVersions(id: string, otherId: string | null) {
  return useQuery<VersionCompareResult>({
    queryKey: ['documents', id, 'versions', 'compare', otherId],
    queryFn: async () => {
      const { data } = await apiClient.get(`/documents/${id}/versions/compare`, {
        params: { other_id: otherId },
      })
      return data
    },
    enabled: !!id && !!otherId,
  })
}

export function useArchiveDocument() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) => {
      const { data } = await apiClient.post<Document>(`/documents/${id}/archive`)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents'] })
    },
  })
}

export function useRestoreVersion() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) => {
      const { data } = await apiClient.post<Document>(`/documents/${id}/restore`)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents'] })
    },
  })
}

export function useSetDocumentExpiry() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, expiresAt }: { id: string; expiresAt: string | null }) => {
      const { data } = await apiClient.put<Document>(`/documents/${id}/expiry`, { expires_at: expiresAt })
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents'] })
    },
  })
}
