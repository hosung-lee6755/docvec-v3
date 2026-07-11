import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../lib/apiClient'

export type DictionaryEntryType = 'stopword' | 'synonym' | 'custom_word'
export type MatchType = 'EXACT' | 'CONTAINS' | 'PREFIX' | 'SUFFIX' | 'REGEX'
export type SynonymDirection = 'ONE_WAY' | 'BIDIRECTIONAL'
export type SynonymProcessingMode = 'NORMALIZE' | 'REPLACE' | 'SEARCH_EXPAND' | 'TAGGING'
export type UserTermType =
  | 'TECHNICAL_TERM' | 'ABBREVIATION' | 'ORGANIZATION' | 'PERSON'
  | 'PRODUCT' | 'PROJECT' | 'POLICY' | 'CUSTOM'
export type UserProcessingRule = 'KEEP' | 'NORMALIZE' | 'REPLACE' | 'TAG' | 'EXTRACT' | 'MASK' | 'IGNORE'

export interface DictionaryEntry {
  id: string
  entry_type: DictionaryEntryType
  term: string
  variants: string[]
  match_type: MatchType | null
  direction: SynonymDirection | null
  processing_mode: SynonymProcessingMode | null
  term_type: UserTermType | null
  processing_rule: UserProcessingRule | null
  pronunciation: string | null
  case_sensitive: boolean
  language: string
  scope: string[]
  description: string | null
  enabled: boolean
  created_at: string
  updated_at: string
}

export interface DictionaryEntryInput {
  term: string
  variants?: string[]
  match_type?: MatchType
  direction?: SynonymDirection
  processing_mode?: SynonymProcessingMode
  term_type?: UserTermType
  processing_rule?: UserProcessingRule
  pronunciation?: string | null
  case_sensitive?: boolean
  language?: string
  scope?: string[]
  description?: string | null
  enabled?: boolean
}

export interface DictionaryImportResult {
  created: number
  updated: number
  skipped: number
  skipped_rows: number[]
}

export function useDictionaryEntries(entryType: DictionaryEntryType) {
  return useQuery<{ items: DictionaryEntry[] }>({
    queryKey: ['dictionary-entries', entryType],
    queryFn: async () => {
      const { data } = await apiClient.get('/admin/dictionary', { params: { entry_type: entryType } })
      return data
    },
  })
}

export function useCreateDictionaryEntry(entryType: DictionaryEntryType) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (input: DictionaryEntryInput) => {
      const { data } = await apiClient.post('/admin/dictionary', { entry_type: entryType, ...input })
      return data as DictionaryEntry
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['dictionary-entries', entryType] })
    },
  })
}

export function useUpdateDictionaryEntry(entryType: DictionaryEntryType) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, ...input }: { id: string } & Partial<DictionaryEntryInput>) => {
      const { data } = await apiClient.patch(`/admin/dictionary/${id}`, input)
      return data as DictionaryEntry
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['dictionary-entries', entryType] })
    },
  })
}

export function useDeleteDictionaryEntry(entryType: DictionaryEntryType) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (entryId: string) => {
      await apiClient.delete(`/admin/dictionary/${entryId}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['dictionary-entries', entryType] })
    },
  })
}

export function useExportDictionaryEntries(entryType: DictionaryEntryType) {
  return useMutation({
    mutationFn: async () => {
      const response = await apiClient.get('/admin/dictionary/export', {
        params: { entry_type: entryType },
        responseType: 'blob',
      })
      const url = URL.createObjectURL(response.data as Blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `dictionary_${entryType}.xlsx`
      link.click()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    },
  })
}

export function useImportDictionaryEntries(entryType: DictionaryEntryType) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (file: File) => {
      const form = new FormData()
      form.append('file', file)
      const { data } = await apiClient.post('/admin/dictionary/import', form, {
        params: { entry_type: entryType },
      })
      return data as DictionaryImportResult
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['dictionary-entries', entryType] })
    },
  })
}
