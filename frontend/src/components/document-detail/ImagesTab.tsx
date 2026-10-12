import { Loader2 } from 'lucide-react'
import type { DocumentImagesResult } from '../../hooks/useDocuments'

interface ImagesTabProps {
  isLoading: boolean
  isError: boolean
  imagesResult: DocumentImagesResult | undefined
  isPdfDoc: boolean
}

export default function ImagesTab({
  isLoading,
  isError,
  imagesResult,
  isPdfDoc,
}: ImagesTabProps) {
  if (isLoading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: 'var(--space-6)' }}>
        <Loader2 size={20} style={{ animation: 'spin 1s linear infinite', color: 'var(--color-text-muted)' }} />
      </div>
    )
  }

  if (isError) {
    return (
      <p style={{ color: '#dc2626', fontSize: 13, margin: 0 }}>
        그림 데이터를 불러오는 중 오류가 발생했습니다.
      </p>
    )
  }

  if (!imagesResult?.images.length) {
    return (
      <p style={{ color: 'var(--color-text-muted)', fontSize: 13, margin: 0 }}>
        추출된 그림이 없습니다.
      </p>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-6)' }}>
      {imagesResult.detected_count != null
        && imagesResult.detected_count > imagesResult.images.length && (
        <p style={{ fontSize: 12, color: 'var(--color-text-muted)', margin: 0 }}>
          {imagesResult.detected_count}개 감지됨 · {imagesResult.images.length}개 표시
          (너무 작거나 중복된 이미지 {imagesResult.detected_count - imagesResult.images.length}개 제외)
        </p>
      )}
      {imagesResult.images.map((img, i) => (
        <div key={i}>
          <div style={{ fontSize: 12, color: 'var(--color-text-muted)', marginBottom: 'var(--space-2)' }}>
            그림 {i + 1}{isPdfDoc ? ` · ${img.page_number}쪽` : ''}
          </div>
          <div style={{
            border: '1px solid #e2e8f0', borderRadius: 'var(--radius-sm)',
            padding: 'var(--space-3)', background: '#f8fafc',
            display: 'flex', justifyContent: 'center',
          }}>
            <img
              src={img.url}
              alt={`그림 ${i + 1}`}
              loading="lazy"
              style={{ maxWidth: '100%', maxHeight: 360, objectFit: 'contain' }}
            />
          </div>
          {img.text && (
            <p style={{
              fontSize: 12, color: 'var(--color-text-muted)', lineHeight: 1.6,
              whiteSpace: 'pre-wrap', wordBreak: 'break-word',
              margin: 'var(--space-2) 0 0',
            }}>
              {img.text}
            </p>
          )}
        </div>
      ))}
    </div>
  )
}
