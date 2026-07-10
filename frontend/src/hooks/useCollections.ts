import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../lib/apiClient'

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
  embedding_model: string
  chunk_max_tokens: number
  chunk_min_tokens: number
  chunk_overlap_tokens: number
  chunk_strategy?: 'size' | 'semantic'
}

export interface UpdateCollectionInput {
  id: string
  name: string
  description?: string
  project_id?: string
  restrict_to_members?: boolean
  embedding_model?: string
  chunk_max_tokens?: number
  chunk_min_tokens?: number
  chunk_overlap_tokens?: number
  chunk_strategy?: 'size' | 'semantic'
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

