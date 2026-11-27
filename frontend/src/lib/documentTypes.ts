// 문서 유형(2026-11-27). 유형에 따라 구조 분석과 청크 분할이 달라진다(backend services/document_type.py).
// 정하는 순서는 문서에 지정한 값, 컬렉션 기본값, 자동 판별 순이다.
export type DocumentType = 'regulation' | 'general'

export const DOCUMENT_TYPE_LABELS: Record<DocumentType, string> = {
  regulation: '규정·법령',
  general: '일반 문서',
}

export const DOCUMENT_TYPE_OPTIONS: { value: DocumentType; label: string }[] = [
  { value: 'regulation', label: DOCUMENT_TYPE_LABELS.regulation },
  { value: 'general', label: DOCUMENT_TYPE_LABELS.general },
]

export const DOCUMENT_TYPE_HINT =
  '규정·법령은 조(제1조 등) 단위로 제목과 청크를 나눕니다. 자동 판별은 제1조부터 조문이 이어지는 문서를 규정으로 봅니다.'

export function documentTypeLabel(value: string | null | undefined): string | null {
  return value && value in DOCUMENT_TYPE_LABELS ? DOCUMENT_TYPE_LABELS[value as DocumentType] : null
}

// 파일마다 고른 유형이 있으면 그것을, 없으면 업로드 전체에 고른 유형을 쓴다. 둘 다 비면 자동(컬렉션 기본값 → 판별)이다
export function resolveUploadDocumentType(fileType: string | undefined, batchType: string): string | undefined {
  return fileType || batchType || undefined
}
