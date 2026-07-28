import { useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../lib/apiClient'

// 메타 정보 생성 설계서(2026-07-23) Phase 2 — author/organization/
// security_level/source_system은 문서 내용에서 자동 생성할 수 없어, 사용자가
// 입력한 값만 PATCH /documents/{id}/metadata로 저장한다. 빈 문자열은 값을
// 지우는 것으로 취급해 null로 변환해 보낸다(자유 텍스트 필드가 "미입력"으로
// 되돌아갈 수 있도록).
export type SecurityLevel = 'Public' | 'Internal' | 'Confidential'

export interface DocumentMetadataUpdate {
  documentId: string
  author?: string | null
  organization?: string | null
  security_level?: SecurityLevel | null
  source_system?: string | null
  // 메타 정보 생성.txt 1절 — hwp/hwpx처럼 자동 추출이 불가능한 문서의
  // document_created_at을 사용자가 직접 입력하는 경로(YYYY-MM-DD 문자열).
  document_created_at?: string | null
}

export function useUpdateDocumentMetadata() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ documentId, ...fields }: DocumentMetadataUpdate) => {
      const payload = Object.fromEntries(
        Object.entries(fields).map(([key, value]) => [key, value === '' ? null : value]),
      )
      const { data } = await apiClient.patch(`/documents/${documentId}/metadata`, payload)
      return data
    },
    onSuccess: (_data, { documentId }) => {
      queryClient.invalidateQueries({ queryKey: ['documents', documentId] })
    },
  })
}
