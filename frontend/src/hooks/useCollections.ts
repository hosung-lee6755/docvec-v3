import type { SecurityLevel } from './useDocumentMetadata'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../lib/apiClient'

// v3 마일스톤 6 — 컬렉션별 검색 설정. 서버 services/search_settings.py와 범위를 맞춘다.
export interface SearchSettings {
  mode: 'hybrid' | 'vector'
  top_k: number
  rerank: boolean
  diversify: boolean
  vector_weight: number
}

export const DEFAULT_SEARCH_SETTINGS: SearchSettings = {
  mode: 'hybrid', top_k: 5, rerank: true, diversify: false, vector_weight: 0.6,
}

export interface Collection {
  id: string
  name: string
  description: string | null
  project_id: string | null
  project_name: string | null
  restrict_to_members: boolean
  qdrant_collection_name: string
  embedding_model: string
  chunk_max_tokens: number
  chunk_min_tokens: number
  chunk_overlap_tokens: number
  chunk_strategy: 'size' | 'semantic'
  default_workflow_id: string | null
  default_workflow_version: number | null
  default_analysis_workflow_id: string | null
  default_analysis_workflow_version: number | null
  // v3: 자체 등급이 없는 문서에 적용할 기본 보안등급(null = 공개)
  default_security_level: 'Public' | 'Internal' | 'Confidential' | null
  // v3 마일스톤 6: 이 컬렉션의 검색과 채팅이 따르는 검색 방식(서버가 기본값을 채워 보낸다)
  search_settings?: SearchSettings
  reembed_status: 'PENDING' | 'RUNNING' | 'COMPLETED' | 'FAILED' | null
  reembed_progress: string | null
  created_at: string
  document_count: number
  is_owner: boolean
  role: 'owner' | 'editor' | 'viewer' | null
}

export interface CollectionListResponse {
  items: Collection[]
}

export interface CollectionMember {
  user_id: string
  email: string
  username: string
  role: 'owner' | 'editor' | 'viewer'
  created_at: string | null
}

export interface CollectionMemberListResponse {
  items: CollectionMember[]
}

export interface InviteMemberInput {
  collectionId: string
  email: string
  role: 'viewer' | 'editor'
}

export interface EmbeddingModelOption {
  key: string
  label: string
  dimension: number
}

export interface CreateCollectionInput {
  name: string
  description?: string
  project_id?: string
  // 임베딩 모델/청킹 설정은 더 이상 컬렉션 생성 화면에서 입력받지 않는다 —
  // 시스템 기본값으로 생성되고, 필요하면 이 컬렉션의 전처리 워크플로우
  // 문서분할/RAG저장 블록에서만 재정의한다.
  default_workflow_id?: string
  default_workflow_version?: number
  default_analysis_workflow_id?: string
  default_analysis_workflow_version?: number
  // 등급이 없는 문서에 적용할 기본 보안등급. 비우면 공개
  default_security_level?: SecurityLevel
}

export interface UpdateCollectionInput {
  id: string
  // 서버는 보낸 필드만 바꾼다. 검색 설정만 저장할 때는 이름을 보내지 않는다
  name?: string
  description?: string
  project_id?: string
  // v3 마일스톤 6: 보내면 반영(null = 기본값으로)
  search_settings?: SearchSettings | null
  restrict_to_members?: boolean
  default_workflow_id?: string | null
  default_workflow_version?: number | null
  clear_default_workflow?: boolean
  default_analysis_workflow_id?: string | null
  default_analysis_workflow_version?: number | null
  clear_default_analysis_workflow?: boolean
  // 보내면 반영(null = 해제). 생략하면 그대로 둔다.
  default_security_level?: 'Public' | 'Internal' | 'Confidential' | null
}

export function useEmbeddingModels() {
  return useQuery<{ items: EmbeddingModelOption[] }>({
    queryKey: ['embedding-models'],
    queryFn: async () => {
      const { data } = await apiClient.get('/collections/embedding-models')
      return data
    },
    staleTime: Infinity,
  })
}

export function useCollections(projectId?: string | null) {
  return useQuery<CollectionListResponse>({
    queryKey: ['collections', projectId ?? null],
    queryFn: async () => {
      const { data } = await apiClient.get('/collections', {
        params: projectId ? { project_id: projectId } : undefined,
      })
      return data
    },
    refetchInterval: (query) => {
      const items = query.state.data?.items ?? []
      const isReembedding = items.some((c) => c.reembed_status === 'PENDING' || c.reembed_status === 'RUNNING')
      return isReembedding ? 3000 : false
    },
  })
}

export function useCreateCollection() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (input: CreateCollectionInput) => {
      const { data } = await apiClient.post('/collections', input)
      return data as Collection
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['collections'] })
    },
  })
}

export function useDeleteCollection() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) => {
      await apiClient.delete(`/collections/${id}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['collections'] })
    },
  })
}

export function useReprocessCollection() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) => {
      const { data } = await apiClient.post(`/collections/${id}/reprocess`)
      return data as { queued: number; skipped: number }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['collections'] })
      queryClient.invalidateQueries({ queryKey: ['documents'] })
    },
  })
}

export function useUpdateCollection() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, ...input }: UpdateCollectionInput) => {
      const { data } = await apiClient.patch(`/collections/${id}`, input)
      return data as Collection
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['collections'] })
    },
  })
}

export function useCollectionMembers(collectionId: string | null) {
  return useQuery<CollectionMemberListResponse>({
    queryKey: ['collection-members', collectionId],
    queryFn: async () => {
      const { data } = await apiClient.get(`/collections/${collectionId}/members`)
      return data
    },
    enabled: !!collectionId,
  })
}

export function useInviteMember() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ collectionId, email, role }: InviteMemberInput) => {
      const { data } = await apiClient.post(`/collections/${collectionId}/invite`, { email, role })
      return data as { message: string; email: string; role: string }
    },
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ['collection-members', variables.collectionId] })
    },
  })
}

export function useRemoveMember() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ collectionId, userId }: { collectionId: string; userId: string }) => {
      await apiClient.delete(`/collections/${collectionId}/members/${userId}`)
    },
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ['collection-members', variables.collectionId] })
    },
  })
}

