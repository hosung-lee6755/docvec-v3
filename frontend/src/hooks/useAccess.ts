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
