import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../lib/apiClient'
import type { SecurityLevel } from './useDocumentMetadata'

// v3 권한 모델 — 사용자 그룹과 문서 접근 허용 목록(ACL).
// 규칙의 정본은 백엔드 app/services/access_policy.py다. 화면은 설정만 하고 판정하지 않는다.

export const SECURITY_LEVELS: SecurityLevel[] = ['Public', 'Internal', 'Confidential']

export const SECURITY_LEVEL_LABELS: Record<SecurityLevel, string> = {
  Public: '공개',
  Internal: '내부',
  Confidential: '대외비',
}

export interface Group {
  id: string
  name: string
  description: string | null
  member_count: number
  created_at: string
  // local=화면에서 관리, ldap=AD에서 동기화(이름·구성원 수정 불가)
  source?: "local" | "ldap"
  // AD에서 다시 생긴 그룹이라 예전 그룹의 문서 권한을 이어받을지 정해야 한다
  has_previous_permissions?: boolean
  // AD가 스스로 만드는 기본 그룹(Domain Admins 등). 문서 접근 허용 선택 목록에서 숨긴다
  is_system?: boolean
}

/** 다시 생긴 AD 그룹이 이어받을 수 있는 예전 그룹의 문서 권한 */
export interface PreviousPermissions {
  previous_group_id: string | null
  document_count: number
  connector_document_count: number
  documents: { id: string; title: string }[]
}

export interface GroupMember {
  user_id: string
  email: string
  username: string
  added_at: string | null
}

export interface GroupDetail extends Group {
  members: GroupMember[]
}

export type PrincipalType = 'user' | 'group'

export interface AclEntry {
  principal_type: PrincipalType
  principal_id: string
  // 삭제된 사용자·그룹은 null — 항목은 제한 유지를 위해 남아 있다.
  display_name: string | null
}

export interface DocumentAcl {
  document_id: string
  security_level: SecurityLevel | null
  effective_security_level: SecurityLevel
  restricted: boolean
  // 등급을 낮추거나 제한을 풀 수 있는지(업로더·컬렉션 소유자만)
  can_relax?: boolean
  // 파일 서버에서 가져온 문서면 true. 권한과 등급은 원천에서 바꾼다.
  source_managed?: boolean
  entries: AclEntry[]
}

const GROUPS_KEY = ['groups'] as const

export function useGroups() {
  return useQuery<{ items: Group[] }>({
    queryKey: GROUPS_KEY,
    queryFn: async () => (await apiClient.get('/groups')).data,
  })
}

export function useGroup(groupId: string | null) {
  return useQuery<GroupDetail>({
    queryKey: ['groups', groupId],
    queryFn: async () => (await apiClient.get(`/groups/${groupId}`)).data,
    enabled: !!groupId,
  })
}

function useInvalidateGroups() {
  const queryClient = useQueryClient()
  return () => queryClient.invalidateQueries({ queryKey: GROUPS_KEY })
}

export function useCreateGroup() {
  const invalidate = useInvalidateGroups()
  return useMutation({
    mutationFn: async (input: { name: string; description?: string | null }) =>
      (await apiClient.post('/groups', input)).data as Group,
    onSuccess: invalidate,
  })
}

export function useUpdateGroup() {
  const invalidate = useInvalidateGroups()
  return useMutation({
    mutationFn: async ({ id, ...input }: { id: string; name?: string; description?: string | null }) =>
      (await apiClient.patch(`/groups/${id}`, input)).data as Group,
    onSuccess: invalidate,
  })
}

export function usePreviousPermissions(groupId: string, enabled: boolean) {
  return useQuery<PreviousPermissions>({
    queryKey: [...GROUPS_KEY, groupId, "previous-permissions"],
    queryFn: async () => (await apiClient.get(`/groups/${groupId}/previous-permissions`)).data,
    enabled,
  })
}

export function useInheritPreviousPermissions() {
  const invalidate = useInvalidateGroups()
  return useMutation({
    mutationFn: async (groupId: string) =>
      (await apiClient.post(`/groups/${groupId}/inherit-previous-permissions`)).data as { moved: number; already_granted: number; sync_failed: number },
    onSuccess: invalidate,
  })
}

export function useDismissPreviousPermissions() {
  const invalidate = useInvalidateGroups()
  return useMutation({
    mutationFn: async (groupId: string) => {
      await apiClient.post(`/groups/${groupId}/dismiss-previous-permissions`)
    },
    onSuccess: invalidate,
  })
}

export function useDeleteGroup() {
  const invalidate = useInvalidateGroups()
  return useMutation({
    mutationFn: async (id: string) => {
      await apiClient.delete(`/groups/${id}`)
    },
    onSuccess: invalidate,
  })
}

export function useAddGroupMember() {
  const invalidate = useInvalidateGroups()
  return useMutation({
    mutationFn: async ({ groupId, userId }: { groupId: string; userId: string }) =>
      (await apiClient.post(`/groups/${groupId}/members`, { user_id: userId })).data as GroupMember,
    onSuccess: invalidate,
  })
}

export function useRemoveGroupMember() {
  const invalidate = useInvalidateGroups()
  return useMutation({
    mutationFn: async ({ groupId, userId }: { groupId: string; userId: string }) => {
      await apiClient.delete(`/groups/${groupId}/members/${userId}`)
    },
    onSuccess: invalidate,
  })
}

// securityLevel을 키에 넣어 문서 등급이 바뀌면 실제 적용 등급도 다시 받아온다.
export function useDocumentAcl(documentId: string, securityLevel: string | null) {
  return useQuery<DocumentAcl>({
    queryKey: ['document-acl', documentId, securityLevel],
    queryFn: async () => (await apiClient.get(`/documents/${documentId}/acl`)).data,
    // 403(편집 권한 없음)은 재시도해도 같다.
    retry: false,
  })
}

export function useReplaceDocumentAcl() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ documentId, entries }: {
      documentId: string
      entries: { principal_type: PrincipalType; principal_id: string }[]
    }) => (await apiClient.put(`/documents/${documentId}/acl`, { entries })).data as DocumentAcl,
    onSettled: (_data, _error, variables) => {
      // 502(인덱스 반영 실패)여도 Postgres에는 저장됐으므로 다시 읽는다.
      queryClient.invalidateQueries({ queryKey: ['document-acl', variables.documentId] })
    },
  })
}
