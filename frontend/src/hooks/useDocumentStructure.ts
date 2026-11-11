import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../lib/apiClient'

export interface DocumentNodeItem {
  id: string
  node_type: string
  level: number | null
  sort_order: number
  parent_node_id: string | null
  page_number: number | null
  span_start: number | null
  span_end: number | null
  text: string | null
  style: Record<string, unknown> | null
  user_corrected: boolean
}

export interface DocumentNodesResult {
  document_id: string
  run_id: string | null
  nodes: DocumentNodeItem[]
}

export function useDocumentNodes(documentId: string, enabled = true) {
  return useQuery<DocumentNodesResult>({
    queryKey: ['documents', documentId, 'nodes'],
    queryFn: async () => {
      const { data } = await apiClient.get(`/documents/${documentId}/nodes`)
      return data
    },
    enabled: enabled && !!documentId,
  })
}

export function useUpdateDocumentNode() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({
      documentId, nodeId, level, nodeType, styleName, fontSize, fontName,
    }: {
      documentId: string; nodeId: string; level?: number; nodeType?: string
      // 메타 정보 생성.txt 2절 — HWP/HWPX/Docling 경로처럼 자동 생성이
      // 불가능한 노드의 style_name/font_size/font_name 수동 보정.
      styleName?: string; fontSize?: number; fontName?: string
    }) => {
      const { data } = await apiClient.patch(`/documents/${documentId}/nodes/${nodeId}`, {
        level: level ?? null,
        node_type: nodeType ?? null,
        style_name: styleName || null,
        font_size: fontSize ?? null,
        font_name: fontName || null,
      })
      return data as DocumentNodeItem
    },
    onSuccess: (_data, { documentId }) => {
      queryClient.invalidateQueries({ queryKey: ['documents', documentId, 'nodes'] })
    },
  })
}

export interface CleaningChangeItem {
  id: string
  rule_id: string | null
  rule_key: string | null
  rule_name: string | null
  node_id: string | null
  before_sample: string | null
  after_sample: string | null
  change_count: number
  sample_matches: string[] | null
  created_at: string
}

export interface CleaningChangesResult {
  document_id: string
  run_id: string | null
  total_changes: number
  distinct_rule_count: number
  changes: CleaningChangeItem[]
}

export function useCleaningChanges(documentId: string, enabled = true) {
  return useQuery<CleaningChangesResult>({
    queryKey: ['documents', documentId, 'cleaning-changes'],
    queryFn: async () => {
      const { data } = await apiClient.get(`/documents/${documentId}/cleaning-changes`)
      return data
    },
    enabled: enabled && !!documentId,
  })
}

export interface DictionaryApplicationItem {
  id: string
  dictionary_type: 'STOPWORD' | 'SYNONYM' | 'USER_DICT'
  entry_id: string | null
  dictionary_version: number
  original_text: string
  normalized_text: string | null
  node_id: string | null
  chunk_id: string | null
  start_offset: number | null
  end_offset: number | null
  reverted: boolean
  created_at: string
  // v3 마일스톤 6: 적용 자리의 앞뒤 문맥(이전 기록은 없음)과 사전 항목 이름
  context_before?: string | null
  context_after?: string | null
  entry_term?: string | null
}

export interface DictionaryApplicationsResult {
  document_id: string
  run_id: string | null
  pending_revert_count: number
  applications: DictionaryApplicationItem[]
  // 이 문서에서 끈 사전 항목 id
  excluded_entry_ids?: string[]
}

export interface DictionaryExclusionItem {
  entry_id: string
  term: string | null
  entry_type: string | null
  created_at: string
}

// 이 문서에서 끈 사전 항목. 재처리 뒤에는 적용 기록이 없어지므로 다시 켜려면 이 목록이 필요하다.
export function useDictionaryExclusions(documentId: string) {
  return useQuery<{ document_id: string; entries: DictionaryExclusionItem[] }>({
    queryKey: ['documents', documentId, 'dictionary-applications', 'exclusions'],
    queryFn: async () => {
      const { data } = await apiClient.get(`/documents/${documentId}/dictionary-exclusions`)
      return data
    },
    enabled: !!documentId,
  })
}

// 문서 하나에서만 사전 항목을 끄거나 다시 켠다. 다음 처리(재처리)부터 반영된다.
export function useToggleDictionaryExclusion() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ documentId, entryId, exclude }: { documentId: string; entryId: string; exclude: boolean }) => {
      const url = `/documents/${documentId}/dictionary-exclusions/${entryId}`
      await (exclude ? apiClient.put(url) : apiClient.delete(url))
    },
    onSuccess: (_data, { documentId }) => {
      queryClient.invalidateQueries({ queryKey: ['documents', documentId, 'dictionary-applications'] })
    },
  })
}

export function useDictionaryApplications(documentId: string, enabled = true) {
  return useQuery<DictionaryApplicationsResult>({
    queryKey: ['documents', documentId, 'dictionary-applications'],
    queryFn: async () => {
      const { data } = await apiClient.get(`/documents/${documentId}/dictionary-applications`)
      return data
    },
    enabled: enabled && !!documentId,
  })
}

export function useRevertDictionaryApplication() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ documentId, appId }: { documentId: string; appId: string }) => {
      const { data } = await apiClient.post(
        `/documents/${documentId}/dictionary-applications/${appId}/revert`,
      )
      return data as DictionaryApplicationItem
    },
    onSuccess: (_data, { documentId }) => {
      queryClient.invalidateQueries({ queryKey: ['documents', documentId, 'dictionary-applications'] })
    },
  })
}

export interface PiiDetectionItem {
  id: string
  entity_type: string
  action: 'MARK' | 'MASK' | 'TOKENIZE' | 'REMOVE' | 'EXCLUDE_EMBEDDING'
  masked_value: string | null
  page_number: number | null
  node_id: string | null
  start_offset: number | null
  end_offset: number | null
  confidence: number | null
  approved_by: string | null
  approved_at: string | null
  rejected: boolean
  created_at: string
}

export interface PiiDetectionsResult {
  document_id: string
  run_id: string | null
  detections: PiiDetectionItem[]
}

export function usePiiDetections(documentId: string, enabled = true) {
  return useQuery<PiiDetectionsResult>({
    queryKey: ['documents', documentId, 'pii'],
    queryFn: async () => {
      const { data } = await apiClient.get(`/documents/${documentId}/pii`)
      return data
    },
    enabled: enabled && !!documentId,
  })
}

export function useApprovePii() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ documentId, detectionId }: { documentId: string; detectionId: string }) => {
      const { data } = await apiClient.post(`/documents/${documentId}/pii/${detectionId}/approve`)
      return data as PiiDetectionItem
    },
    onSuccess: (_data, { documentId }) => {
      queryClient.invalidateQueries({ queryKey: ['documents', documentId, 'pii'] })
    },
  })
}

export function useRejectPii() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ documentId, detectionId }: { documentId: string; detectionId: string }) => {
      const { data } = await apiClient.post(`/documents/${documentId}/pii/${detectionId}/reject`)
      return data as PiiDetectionItem
    },
    onSuccess: (_data, { documentId }) => {
      queryClient.invalidateQueries({ queryKey: ['documents', documentId, 'pii'] })
    },
  })
}

export function useRevealPii() {
  return useMutation({
    mutationFn: async ({ documentId, detectionId }: { documentId: string; detectionId: string }) => {
      const { data } = await apiClient.post(`/documents/${documentId}/pii/${detectionId}/reveal`)
      return data as { value: string }
    },
  })
}
