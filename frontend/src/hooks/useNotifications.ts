import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../lib/apiClient'

// 전체 점검 2-7 — 문서 처리 실패, 검토 대기, 파일 서버 동기화 실패 알림.
// 서버가 밀어 주지 않으므로 주기적으로 다시 읽는다. 창으로 돌아올 때도 한 번 읽는다.

export type NotificationKind =
  | 'document_failed'
  | 'review_waiting'
  | 'sync_failed'
  | 'inquiry_created'
  | 'inquiry_replied'
  | 'inquiry_followup'

export interface AppNotification {
  id: string
  kind: NotificationKind
  title: string
  body: string | null
  link: string | null
  created_at: string
  read_at: string | null
}

export interface NotificationList {
  items: AppNotification[]
  unread_count: number
}

const KEY = ['notifications'] as const
const REFRESH_MS = 60_000

export function useNotifications() {
  return useQuery<NotificationList>({
    queryKey: KEY,
    queryFn: async () => (await apiClient.get('/notifications', { params: { limit: 30 } })).data,
    refetchInterval: REFRESH_MS,
    refetchOnWindowFocus: true,
  })
}

function useInvalidate() {
  const queryClient = useQueryClient()
  return () => queryClient.invalidateQueries({ queryKey: KEY })
}

export function useMarkNotificationRead() {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: async (id: string) => (await apiClient.post(`/notifications/${id}/read`)).data,
    onSuccess: invalidate,
  })
}

export function useMarkAllNotificationsRead() {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: async () => (await apiClient.post('/notifications/read-all')).data,
    onSuccess: invalidate,
  })
}

export function useDeleteNotification() {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: async (id: string) => {
      await apiClient.delete(`/notifications/${id}`)
    },
    onSuccess: invalidate,
  })
}
