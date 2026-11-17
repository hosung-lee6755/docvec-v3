import { Loader2 } from 'lucide-react'
import { usePdfBlobUrl } from '../../hooks/usePdfBlobUrl'

export interface PreviewResult {
  kind: 'pdf' | 'html'
  url: string
  approximate?: boolean
}

interface OriginalPagePreviewProps {
  previewResult: PreviewResult | undefined
  isPreviewError: boolean
  pageNumber: number | null
  height?: number
}

const DEFAULT_HEIGHT = 420

/** 탭을 옮기지 않고 원문의 해당 쪽을 바로 보여 준다(구조 탭 오른쪽 상세에서 쓴다). */
export default function OriginalPagePreview({
  previewResult, isPreviewError, pageNumber, height = DEFAULT_HEIGHT,
}: OriginalPagePreviewProps) {
  const isPdf = previewResult?.kind === 'pdf'
  const pdfBlob = usePdfBlobUrl(isPdf ? previewResult?.url : undefined)
  const page = Math.max(pageNumber ?? 1, 1)

  if (isPreviewError) {
    return <p style={{ fontSize: 12, color: 'var(--color-text-muted)', margin: 0 }}>원문 미리보기를 만들지 못했습니다.</p>
  }
  let src: string | undefined
  if (previewResult?.url) {
    if (!isPdf) src = previewResult.url
    else if (pdfBlob.blobUrl) src = `${pdfBlob.blobUrl}#page=${page}`
    else if (pdfBlob.isError) src = `${previewResult.url}#page=${page}`
  }
  if (!src) {
    return (
      <div role="status" aria-label="원문 불러오는 중" style={{ display: 'flex', justifyContent: 'center', padding: 'var(--space-4)' }}>
        <Loader2 size={18} style={{ animation: 'spin 1s linear infinite', color: 'var(--color-text-muted)' }} />
      </div>
    )
  }
  return (
    <iframe
      key={isPdf ? `${src}` : 'html'}
      src={src}
      title={isPdf ? `원문 ${page}쪽` : '원문'}
      style={{
        width: '100%', height, border: '1px solid var(--color-border)',
        borderRadius: 'var(--radius-sm)', background: 'var(--color-surface)',
      }}
    />
  )
}
