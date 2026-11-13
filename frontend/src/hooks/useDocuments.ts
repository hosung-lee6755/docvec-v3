import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../lib/apiClient'
import { PROCESSING_STATUSES } from '../lib/documentStatus'

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
  active_run_id: string | null
  // 메타 정보 생성 설계서(2026-07-23) — title/language/category/page_count는
  // 문서 내용에서 자동 생성(Phase 1), author/organization/security_level/
  // source_system은 PATCH /documents/{id}/metadata로 사용자가 입력해야만
  // 채워짐(Phase 2). 전부 null이 기본값.
  title: string | null
  language: string | null
  category: string | null
  page_count: number | null
  author: string | null
  organization: string | null
  security_level: string | null
  source_system: string | null
  // 메타 정보 생성.txt 1절 후속(2026-07-24) — checksum/parser_version/
  // source_path/file_type은 기존 file_hash/pipeline_version/minio_key/
  // mime_type 컬럼을 스펙 필드명으로 노출한 것(신규 컬럼 아님).
  // document_created_at은 문서 자체의 작성일(created_at=DB 저장 시각과 별개) —
  // docx/pdf는 자동 추출, hwp/hwpx는 PATCH /documents/{id}/metadata로 수동 입력.
  checksum: string | null
  parser_version: Record<string, unknown> | null
  source_path: string | null
  file_type: string | null
  document_created_at: string | null
  // 사용자가 직접 수정한 필드 이름(title/language/category 중 일부). 자동 생성값을
  // 덮어쓴 상태를 표시하고, reset_fields로 되돌릴 수 있는지 판단하는 데 쓴다.
  user_edited_fields?: string[]
  // v3 마일스톤 6: 최근 처리의 품질 판정과 OCR 신뢰도가 기준보다 낮은 쪽 번호
  quality_status?: string | null
  low_ocr_pages?: number[]
  // 문서 버전·수명주기(M7). lineage_id는 같은 문서의 모든 버전이 공유하는 id이고,
  // pending은 새 버전이 아직 처리 중인 상태다. 검색에는 current 버전만 쓰인다.
  lineage_id: string
  version_number: number
  lifecycle_state: DocumentLifecycleState
  expires_at: string | null
  archived_at: string | null
}

export type DocumentLifecycleState = 'pending' | 'current' | 'superseded' | 'archived'
export type DocumentLifecycleFilter = 'current' | 'archived' | 'superseded' | 'all'
export type DocumentQualityFilter = 'low_ocr' | 'warning' | 'failure'

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
  quality?: DocumentQualityFilter | ''
  // 비우면 이전 버전(superseded)만 숨긴 기본 목록이다.
  lifecycle?: DocumentLifecycleFilter | ''
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
    quality,
    lifecycle,
    sortBy = 'created_at',
    order = 'desc',
  } = options

  return useQuery<DocumentListResponse>({
    queryKey: ['documents', page, limit, collectionId, projectId, status, filename, quality, lifecycle, sortBy, order],
    queryFn: async () => {
      const { data } = await apiClient.get('/documents', {
        params: {
          page,
          limit,
          collection_id: collectionId || undefined,
          project_id: projectId || undefined,
          status: status || undefined,
          filename: filename || undefined,
          quality: quality || undefined,
          lifecycle: lifecycle || undefined,
          sort_by: sortBy,
          order,
        },
      })
      return data
    },
    refetchInterval: (query) => {
      // status=WAITING_REVIEW로 필터링된 조회는 정의상 결과에 처리중 상태가 절대
      // 나오지 않아 아래 hasProcessing 조건이 항상 false다 — 그래서 사이드바
      // 배지(useWaitingReviewCount)가 백그라운드에서 새로 WAITING_REVIEW가 된
      // 문서를 반영하지 못하고 마운트 시점 값에 고정되는 버그가 있었다(사용자
      // 확인 2026-07-21, "검토대기문서는 3건인데... 1이라는 숫자가 있다").
      if (status?.split(',').some((s) => s === 'WAITING_REVIEW' || s === 'FAILED')) return 15000
      const items = query.state.data?.items ?? []
      const hasProcessing = items.some((d) => PROCESSING_STATUSES.includes(d.status))
      return hasProcessing ? 3000 : false
    },
  })
}

export function useWaitingReviewCount() {
  const { data } = useDocuments({ status: 'WAITING_REVIEW', limit: 1 })
  return data?.total ?? 0
}

export function useFailedCount() {
  const { data } = useDocuments({ status: 'FAILED', limit: 1 })
  return data?.total ?? 0
}

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
  // Docling 요소 중 type=="picture" 개수 — 작은/중복 이미지 필터링 전 원본 개수.
  // legacy 엔진 문서(elements 없음)는 null.
  detected_count: number | null
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
  embedded: boolean
  // 메타 정보 생성 설계서(2026-07-23) Phase 4 — token_count/chunk_type/
  // keywords/embedding_model/element_id/workflow_version/dictionary_version은
  // tree 기반 청킹 전략(paragraph/section_aware/table_unit)에서만 채워짐.
  // total_chunks/char_count는 DB에 저장되지 않고 응답 조립 시점에 계산됨.
  token_count: number | null
  chunk_type: string | null
  keywords: string[] | null
  embedding_model: string | null
  element_id: string | null
  prev_chunk_id: string | null
  next_chunk_id: string | null
  workflow_version: number | null
  dictionary_version: number | null
  total_chunks: number
  char_count: number
  section_path: string[] | null
  // 메타 정보 생성.txt 3절 후속(2026-07-24) — heading_path는 section_path와
  // 동일한 데이터(스펙 필드명 노출용). language/source_file/version은
  // DocumentChunk(Postgres) 실컬럼.
  heading_path: string[] | null
  language: string | null
  source_file: string | null
  version: string | null
  // Chunk 계층형 Parent Retrieval(메타 정보 생성.txt 3절, Phase 9) — "상위
  // 청크 보기" 토글용으로 인라인 제공(parent 자체는 목록에 없음).
  parent_chunk_text: string | null
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
    onError: (_err, { docId }) => {
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
    onError: (_err, { docId }) => {
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
      queryClient.invalidateQueries({ queryKey: ['documents', docId, 'chunks'] })
      queryClient.invalidateQueries({ queryKey: ['documents', docId, 'content'] })
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
    onError: (_err, id) => {
      queryClient.invalidateQueries({ queryKey: ['documents', id] })
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
    onError: (_err, { docId }) => {
      queryClient.invalidateQueries({ queryKey: ['documents', docId] })
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
    onError: (_err, { docId }) => {
      queryClient.invalidateQueries({ queryKey: ['documents', docId] })
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
    onError: (_err, { docId }) => {
      queryClient.invalidateQueries({ queryKey: ['documents', docId] })
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

export interface UploadDocumentInput {
  file: File
  collection_id?: string
  skip_review?: boolean
  workflow_version_id?: string
  // true면 같은 이름의 기존 문서에 새 버전으로 잇지 않고 별개 문서로 올린다.
  new_document?: boolean
}

export interface UploadDocumentResult {
  id: string
  // 기존 문서의 몇 번째 버전인지. 1이면 새 문서다.
  version_number?: number | null
}

function appendUploadOptions(form: FormData, input: Omit<UploadDocumentInput, 'file'>) {
  if (input.collection_id) form.append('collection_id', input.collection_id)
  if (input.skip_review) form.append('skip_review', 'true')
  if (input.workflow_version_id) form.append('workflow_version_id', input.workflow_version_id)
  if (input.new_document) form.append('new_document', 'true')
}

export function useUploadDocument() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ file, ...options }: UploadDocumentInput) => {
      const form = new FormData()
      form.append('file', file)
      appendUploadOptions(form, options)
      const { data } = await apiClient.post<UploadDocumentResult>('/documents/upload', form)
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
  version_number?: number | null
}

export interface BulkUploadResponse {
  total_entries: number
  queued: number
  results: BulkUploadItemResult[]
}

export function useUploadZip() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ file, ...options }: UploadDocumentInput) => {
      const form = new FormData()
      form.append('file', file)
      appendUploadOptions(form, options)
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
      queryClient.invalidateQueries({ queryKey: ['documents', id, 'chunks'] })
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

export interface BatchReprocessItemResult {
  id: string
  status: 'queued' | 'skipped' | 'failed'
  run_id: string | null
  detail: string | null
}

export function useBatchReprocessDocuments() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (ids: string[]) => {
      const { data } = await apiClient.post<{ results: BatchReprocessItemResult[] }>(
        '/documents/batch-reprocess', { ids },
      )
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents'] })
    },
  })
}
