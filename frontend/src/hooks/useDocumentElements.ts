import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../lib/apiClient'

// Docling 도입 설계서(2026-07-23) Phase 4 — Document.elements(JSON 컬럼,
// Docling 엔진으로 처리된 PDF만 채워짐)를 그대로 노출한다. bbox는 백엔드
// content/metadata 그대로 통과시키는 dict라 타입이 넓다.
export interface DocumentElementItem {
  id: string
  page: number | null
  type: string
  bbox: number[] | null
  content: { text?: string; markdown?: string; [key: string]: unknown }
  metadata: {
    section_path?: string[]
    is_header?: boolean
    is_footer?: boolean
    confidence?: number
    detected_as?: string
    level?: number | null
    // 메타 정보 생성 설계서(2026-07-23) Phase 3 — order는 읽기 순서,
    // is_caption은 caption 타입 요소 여부, table_rows/table_cols는 TABLE
    // 요소 전용, image_path는 PICTURE 요소와 Document.images의 best-effort
    // 매치 결과(매치 실패 시 null). style/font_size/font_name은 Docling이
    // 제공하지 않아 항상 null.
    order?: number
    is_caption?: boolean
    table_rows?: number
    table_cols?: number
    image_path?: string | null
    // 메타 정보 생성.txt 2절 — Docling 라이브러리가 폰트 정보를 노출하지
    // 않아 항상 null(자동 생성 불가), PATCH로 수동 입력해야 채워진다.
    style?: string | null
    font_size?: number | null
    font_name?: string | null
    [key: string]: unknown
  }
  span_start: number | null
  span_end: number | null
  user_corrected: boolean
  correction_notes: string | null
}

export interface DocumentElementsResult {
  document_id: string
  elements: DocumentElementItem[]
}

export function useDocumentElements(documentId: string, enabled = true) {
  return useQuery<DocumentElementsResult>({
    queryKey: ['documents', documentId, 'elements'],
    queryFn: async () => {
      const { data } = await apiClient.get(`/documents/${documentId}/elements`)
      return data
    },
    enabled: enabled && !!documentId,
  })
}

export function useUpdateDocumentElement() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({
      documentId, elementId, markdown, correctionNotes, style, fontSize, fontName,
    }: {
      documentId: string; elementId: string; markdown: string; correctionNotes?: string
      style?: string; fontSize?: number; fontName?: string
    }) => {
      const { data } = await apiClient.patch(`/documents/${documentId}/elements/${elementId}`, {
        markdown,
        correction_notes: correctionNotes ?? null,
        style: style || null,
        font_size: fontSize ?? null,
        font_name: fontName || null,
      })
      return data as DocumentElementItem
    },
    onSuccess: (_data, { documentId }) => {
      queryClient.invalidateQueries({ queryKey: ['documents', documentId, 'elements'] })
    },
  })
}
