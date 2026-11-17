import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../lib/apiClient'

// 관리자 문의. 일반 사용자는 자기 문의만 받고, 관리자는 전부 받는다(서버가 거른다).

export type InquiryCategory = 'error' | 'question' | 'request' | 'other'
export type InquiryStatus = 'open' | 'in_progress' | 'resolved' | 'closed'

export interface InquiryListItem {
  id: string
  title: string
  category: InquiryCategory
  status: InquiryStatus
  author_id: string
  author_name: string
  document_id: string | null
  created_at: string
  updated_at: string
}

export interface InquiryList {
  total: number
  items: InquiryListItem[]
}

export interface InquiryMessage {
  id: string
  author_id: string
  author_name: string
  is_admin: boolean
  body: string
  created_at: string
}

export interface InquiryDetail extends InquiryListItem {
  error_snapshot: string | null
  document: { id: string; original_filename: string; status: string } | null
  messages: InquiryMessage[]
  is_author: boolean
  has_admin_reply: boolean
  can_edit: boolean
  can_reply: boolean
  can_delete: boolean
}

export interface InquiryCreateInput {
  title: string
  body: string
  category: InquiryCategory
  document_id?: string
}

export interface InquiryUpdateInput {
  title?: string
  body?: string
  category?: InquiryCategory
  status?: InquiryStatus
}

export interface InquiryListParams {
  status?: InquiryStatus | 'all'
  limit?: number
  offset?: number
}

const KEY = ['inquiries'] as const

export function useInquiries(params: InquiryListParams = {}) {
  const { status = 'all', limit = 20, offset = 0 } = params
  return useQuery<InquiryList>({
    queryKey: [...KEY, 'list', { status, limit, offset }],
    queryFn: async () => (await apiClient.get('/inquiries', {
      params: { ...(status === 'all' ? {} : { status }), limit, offset },
    })).data,
  })
}

/** 관리자 메뉴의 접수 대기 건수. 열린 문의 수만 가볍게 받는다. */
export function useOpenInquiryCount(enabled = true) {
  return useQuery<InquiryList>({
    queryKey: [...KEY, 'open-count'],
    queryFn: async () => (await apiClient.get('/inquiries', { params: { status: 'open', limit: 1 } })).data,
    enabled,
    refetchInterval: 60_000,
  })
}

export function useInquiry(inquiryId: string | undefined) {
  return useQuery<InquiryDetail>({
    queryKey: [...KEY, 'detail', inquiryId],
    queryFn: async () => (await apiClient.get(`/inquiries/${inquiryId}`)).data,
    enabled: Boolean(inquiryId),
  })
}

function useInvalidateInquiries() {
  const queryClient = useQueryClient()
  return () => queryClient.invalidateQueries({ queryKey: KEY })
}

export function useCreateInquiry() {
  const invalidate = useInvalidateInquiries()
  return useMutation<InquiryDetail, unknown, InquiryCreateInput>({
    mutationFn: async (input) => (await apiClient.post('/inquiries', input)).data,
    onSuccess: invalidate,
  })
}

export function useAddInquiryMessage(inquiryId: string) {
  const invalidate = useInvalidateInquiries()
  return useMutation<InquiryMessage, unknown, { body: string }>({
    mutationFn: async (input) => (await apiClient.post(`/inquiries/${inquiryId}/messages`, input)).data,
    onSuccess: invalidate,
  })
}

export function useUpdateInquiry(inquiryId: string) {
  const invalidate = useInvalidateInquiries()
  return useMutation<InquiryDetail, unknown, InquiryUpdateInput>({
    mutationFn: async (input) => (await apiClient.patch(`/inquiries/${inquiryId}`, input)).data,
    onSuccess: invalidate,
  })
}

export function useDeleteInquiry() {
  const invalidate = useInvalidateInquiries()
  return useMutation<void, unknown, string>({
    mutationFn: async (inquiryId) => { await apiClient.delete(`/inquiries/${inquiryId}`) },
    onSuccess: invalidate,
  })
}

