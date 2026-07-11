import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../lib/apiClient'

export interface Document {
  id: string
  filename: string
  original_filename: string
  status: string
  file_size: number
  collection_id: string | null
  created_at: string
  updated_at: string
  error_message: string | null
  parsed_text: string | null
  ocr_used: boolean
  summary: string | null
  summary_status: string
  tags: string[] | null
  suggested_tags: string[] | null
  metadata_status: string
}

export interface DocumentListResponse {
  items: Document[]
  total: number
  page: number
  limit: number
}

export type DocumentSortBy = 'created_at' | 'filename' | 'file_size' | 'status'
export type SortOrder = 'asc' | 'desc'

export interface UseDocumentsOptions {
  page?: number
  limit?: number
  collectionId?: string
  projectId?: string
  status?: string
  filename?: string
  sortBy?: DocumentSortBy
  order?: SortOrder
}

export function useDocuments(options: UseDocumentsOptions = {}) {
  const {
    page = 1,
    limit = 20,
    collectionId,
    projectId,
    status,
    filename,
    sortBy = 'created_at',
    order = 'desc',
  } = options

  return useQuery<DocumentListResponse>({
    queryKey: ['documents', page, limit, collectionId, projectId, status, filename, sortBy, order],
    queryFn: async () => {
      const { data } = await apiClient.get('/documents', {
        params: {
          page,
          limit,
          collection_id: collectionId || undefined,
          project_id: projectId || undefined,
          status: status || undefined,
          filename: filename || undefined,
          sort_by: sortBy,
          order,
        },
      })
      return data
    },
    refetchInterval: (query) => {
      const items = query.state.data?.items ?? []
      const hasProcessing = items.some((d) =>
        ['QUEUED', 'INGESTING', 'PARSING', 'STRUCTURING', 'NORMALIZING', 'CHUNKING', 'EMBEDDING', 'UPLOADING'].includes(d.status)
      )
      return hasProcessing ? 3000 : false
    },
  })
}

const PROCESSING_STATUSES = [
  'QUEUED', 'INGESTING', 'PARSING', 'STRUCTURING',
  'NORMALIZING', 'CHUNKING', 'EMBEDDING', 'UPLOADING',
]

export function useDocument(id: string) {
  return useQuery<Document>({
    queryKey: ['documents', id],
    queryFn: async () => {
      const { data } = await apiClient.get(`/documents/${id}`)
      return data
    },
    enabled: !!id,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      const summaryStatus = query.state.data?.summary_status
      const isProcessing = status && PROCESSING_STATUSES.includes(status)
      // Summary generation only starts once a doc reaches INDEXED, so only poll
      // for it there — otherwise a REVIEW_PENDING doc (summary_status defaults
      // to PENDING before it's ever indexed) would poll indefinitely while
      // waiting on the user, which never happened before this feature.
      const isSummarizing = status === 'INDEXED' && (summaryStatus === 'PENDING' || summaryStatus === 'GENERATING')
      return isProcessing || isSummarizing ? 3000 : false
    },
  })
}

export interface DocumentChunk {
  chunk_index: number
  text: string
}

export interface DocumentContent {
  document_id: string
  chunks: DocumentChunk[]
  full_text: string
  chunk_count: number
}

export function useDocumentContent(id: string, enabled: boolean) {
  return useQuery<DocumentContent>({
    queryKey: ['documents', id, 'content'],
    queryFn: async () => {
      const { data } = await apiClient.get(`/documents/${id}/content`)
      return data
    },
    enabled: enabled && !!id,
    staleTime: Infinity,
  })
}

export interface DocumentTable {
  page_number: number
  rows: string[][]
}

export interface DocumentTablesResult {
  document_id: string
  tables: DocumentTable[]
}

export function useDocumentTables(id: string, enabled: boolean) {
  return useQuery<DocumentTablesResult>({
    queryKey: ['documents', id, 'tables'],
    queryFn: async () => {
      const { data } = await apiClient.get(`/documents/${id}/tables`)
      return data
    },
    enabled: enabled && !!id,
    staleTime: Infinity,
  })
}

export interface DocumentImage {
  page_number: number
  text: string
  url: string
}

export interface DocumentImagesResult {
  document_id: string
  images: DocumentImage[]
}

export function useDocumentImages(id: string, enabled: boolean) {
  return useQuery<DocumentImagesResult>({
    queryKey: ['documents', id, 'images'],
    queryFn: async () => {
      const { data } = await apiClient.get(`/documents/${id}/images`)
      return data
    },
    enabled: enabled && !!id,
    // Presigned image URLs expire after 1h — don't cache them indefinitely.
    staleTime: 30 * 60 * 1000,
  })
}

export interface DocumentChunk2 {
  id: string
  chunk_index: number
  text: string
  page_number: number | null
  disabled: boolean
  edited: boolean
  hit_count: number
}

export interface DocumentChunksResult {
  document_id: string
  chunks: DocumentChunk2[]
}

export function useDocumentChunks(id: string, enabled: boolean) {
  return useQuery<DocumentChunksResult>({
    queryKey: ['documents', id, 'chunks'],
    queryFn: async () => {
      const { data } = await apiClient.get(`/documents/${id}/chunks`)
      return data
    },
    enabled: enabled && !!id,
  })
}

export function useUpdateChunk() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ docId, chunkId, text, disabled }: {
      docId: string
      chunkId: string
      text?: string
      disabled?: boolean
    }) => {
      const { data } = await apiClient.patch(`/documents/${docId}/chunks/${chunkId}`, {
        text: text ?? null,
        disabled: disabled ?? null,
      })
      return data
    },
    onSuccess: (_data, { docId }) => {
      queryClient.invalidateQueries({ queryKey: ['documents', docId, 'chunks'] })
      queryClient.invalidateQueries({ queryKey: ['documents', docId, 'content'] })
    },
  })
}

export function useDeleteChunk() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ docId, chunkId }: { docId: string; chunkId: string }) => {
      await apiClient.delete(`/documents/${docId}/chunks/${chunkId}`)
    },
    onSuccess: (_data, { docId }) => {
      queryClient.invalidateQueries({ queryKey: ['documents', docId, 'chunks'] })
      queryClient.invalidateQueries({ queryKey: ['documents', docId, 'content'] })
    },
  })
}

export interface DocumentRevision {
  id: string
  source: string
  created_by: string | null
  created_at: string
  text_length: number
  preview: string
}

export interface DocumentRevisionsResult {
  document_id: string
  revisions: DocumentRevision[]
}

export function useDocumentRevisions(id: string, enabled: boolean) {
  return useQuery<DocumentRevisionsResult>({
    queryKey: ['documents', id, 'revisions'],
    queryFn: async () => {
      const { data } = await apiClient.get(`/documents/${id}/revisions`)
      return data
    },
    enabled: enabled && !!id,
  })
}

export function useRestoreRevision() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ docId, revisionId }: { docId: string; revisionId: string }) => {
      const { data } = await apiClient.post(`/documents/${docId}/revisions/${revisionId}/restore`)
      return data
    },
    onSuccess: (_data, { docId }) => {
      queryClient.setQueryData<Document>(['documents', docId], (old) =>
        old ? { ...old, status: 'CHUNKING' } : old
      )
      queryClient.invalidateQueries({ queryKey: ['documents', docId, 'revisions'] })
    },
  })
}

export function useRetryDocument() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) => {
      const { data } = await apiClient.post(`/documents/${id}/retry`)
      return data
    },
    onSuccess: (_data, id) => {
      queryClient.invalidateQueries({ queryKey: ['documents', id] })
      queryClient.invalidateQueries({ queryKey: ['documents'] })
    },
  })
}

export function useAllTags(enabled = true) {
  return useQuery<{ tags: string[] }>({
    queryKey: ['documents', 'all-tags'],
    queryFn: async () => {
      const { data } = await apiClient.get('/documents/tags')
      return data
    },
    enabled,
    staleTime: 60 * 1000,
  })
}

export function useUpdateDocumentTags() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ docId, tags }: { docId: string; tags: string[] }) => {
      const { data } = await apiClient.patch(`/documents/${docId}/tags`, { tags })
      return data as { tags: string[] }
    },
    onSuccess: (data, { docId }) => {
      queryClient.setQueryData<Document>(['documents', docId], (old) =>
        old ? { ...old, tags: data.tags } : old
      )
    },
  })
}

export function useAcceptTagSuggestion() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ docId, tag }: { docId: string; tag: string }) => {
      const { data } = await apiClient.post(`/documents/${docId}/tags/accept-suggestion`, { tag })
      return data as { tags: string[]; suggested_tags: string[] | null }
    },
    onSuccess: (data, { docId }) => {
      queryClient.setQueryData<Document>(['documents', docId], (old) =>
        old ? { ...old, tags: data.tags, suggested_tags: data.suggested_tags } : old
      )
    },
  })
}

export function useDismissTagSuggestion() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ docId, tag }: { docId: string; tag: string }) => {
      const { data } = await apiClient.post(`/documents/${docId}/tags/dismiss-suggestion`, { tag })
      return data as { suggested_tags: string[] | null }
    },
    onSuccess: (data, { docId }) => {
      queryClient.setQueryData<Document>(['documents', docId], (old) =>
        old ? { ...old, suggested_tags: data.suggested_tags } : old
      )
    },
  })
}

export function useDocumentFileUrl(id: string, enabled: boolean) {
  return useQuery<{ url: string }>({
    queryKey: ['documents', id, 'file-url'],
    queryFn: async () => {
      const { data } = await apiClient.get(`/documents/${id}/download`)
      return data
    },
    enabled: enabled && !!id,
    // Presigned URL is valid for 24h; refresh well before expiry.
    staleTime: 10 * 60 * 1000,
  })
}

export function useDocumentPreview(id: string, enabled: boolean) {
  return useQuery<{ url: string; kind: 'pdf' | 'html'; approximate: boolean }>({
    queryKey: ['documents', id, 'preview'],
    queryFn: async () => {
      const { data } = await apiClient.get(`/documents/${id}/preview`)
      return data
    },
    enabled: enabled && !!id,
    staleTime: 10 * 60 * 1000,
    retry: false,
  })
}

export interface DocumentPageText {
  page_number: number
  text: string
}

export function useDocumentPagesText(id: string, enabled: boolean) {
  return useQuery<{ document_id: string; pages: DocumentPageText[] }>({
    queryKey: ['documents', id, 'pages-text'],
    queryFn: async () => {
      const { data } = await apiClient.get(`/documents/${id}/pages-text`)
      return data
    },
    enabled: enabled && !!id,
    staleTime: 60 * 1000,
  })
}

export function useDownloadDocument() {
  return useMutation({
    mutationFn: async (id: string) => {
      const { data } = await apiClient.get<{ url: string }>(`/documents/${id}/download`)
      return data.url
    },
  })
}

export function useUploadDocument() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({
      file,
      collection_id,
      skip_review,
    }: {
      file: File
      collection_id?: string
      skip_review?: boolean
    }) => {
      const form = new FormData()
      form.append('file', file)
      if (collection_id) form.append('collection_id', collection_id)
      if (skip_review) form.append('skip_review', 'true')
      const { data } = await apiClient.post('/documents/upload', form)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents'] })
    },
  })
}

export interface BulkUploadItemResult {
  filename: string
  status: 'queued' | 'duplicate' | 'skipped' | 'failed'
  document_id: string | null
  detail: string | null
}

export interface BulkUploadResponse {
  total_entries: number
  queued: number
  results: BulkUploadItemResult[]
}

export function useUploadZip() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({
      file,
      collection_id,
      skip_review,
    }: {
      file: File
      collection_id?: string
      skip_review?: boolean
    }) => {
      const form = new FormData()
      form.append('file', file)
      if (collection_id) form.append('collection_id', collection_id)
      if (skip_review) form.append('skip_review', 'true')
      const { data } = await apiClient.post<BulkUploadResponse>('/documents/upload-zip', form)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents'] })
    },
  })
}

export function useProceedDocument() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, editedText }: { id: string; editedText?: string }) => {
      const { data } = await apiClient.post(`/documents/${id}/proceed`, {
        edited_text: editedText ?? null,
      })
      return data
    },
    onSuccess: (_data, { id }) => {
      // Optimistically flip status so polling (gated on PROCESSING_STATUSES)
      // activates immediately instead of racing the Celery task's first write.
      // Do NOT invalidate the doc query here — an immediate refetch could still
      // observe the pre-transition REVIEW_PENDING row and clobber this update,
      // silently killing the poll loop. The 3s refetchInterval will pick up the
      // real status once the task has actually committed it.
      queryClient.setQueryData<Document>(['documents', id], (old) =>
        old ? { ...old, status: 'CHUNKING' } : old
      )
      queryClient.invalidateQueries({ queryKey: ['documents', id, 'jobs'] })
    },
    onError: (_err, { id }) => {
      // The optimistic CHUNKING flip must be rolled back on failure (e.g. 409
      // status conflict), otherwise the UI is stuck showing a processing state
      // that never actually started.
      queryClient.invalidateQueries({ queryKey: ['documents', id] })
    },
  })
}

export function useReprocessDocument() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, editedText }: { id: string; editedText: string }) => {
      const { data } = await apiClient.post(`/documents/${id}/reprocess`, {
        edited_text: editedText,
      })
      return data
    },
    onSuccess: (_data, { id }) => {
      // Same optimistic-flip rationale as useProceedDocument: avoid a refetch
      // racing the Celery task's first write and clobbering this update.
      queryClient.setQueryData<Document>(['documents', id], (old) =>
        old ? { ...old, status: 'CHUNKING' } : old
      )
      queryClient.invalidateQueries({ queryKey: ['documents', id, 'jobs'] })
      queryClient.invalidateQueries({ queryKey: ['documents', id, 'content'] })
    },
    onError: (_err, { id }) => {
      queryClient.invalidateQueries({ queryKey: ['documents', id] })
    },
  })
}

export function useDeleteDocument() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) => {
      await apiClient.delete(`/documents/${id}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents'] })
    },
  })
}

export function useBatchDeleteDocuments() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (ids: string[]) => {
      await apiClient.delete('/documents/batch', { data: { ids } })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents'] })
    },
  })
}
