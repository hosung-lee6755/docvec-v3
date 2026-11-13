import { Loader2 } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { usePdfBlobUrl } from '../../hooks/usePdfBlobUrl'
import { ViewModeToggle } from './documentDetailParts'
import { toBlocksJson } from './documentDetailHelpers'
import { ErrorText } from '../ui'

interface Page {
  page_number: number
  text: string
}

interface PreviewResult {
  kind: 'pdf' | 'html'
  url: string
  approximate?: boolean
}

interface OriginalTabProps {
  isContentLoading: boolean
  isPreviewError: boolean
  previewError?: unknown
  content: { full_text: string; chunk_count: number } | undefined
  pagesTextResult: { pages: Page[] } | undefined
  previewResult: PreviewResult | undefined
  isPdfDoc: boolean
  originalPage: number
  showJson: boolean
  onOriginalPageChange: (page: number) => void
  onShowJsonChange: (v: boolean) => void
}

export default function OriginalTab({
  isContentLoading,
  isPreviewError,
  previewError,
  content,
  pagesTextResult,
  previewResult,
  isPdfDoc,
  originalPage,
  showJson,
  onOriginalPageChange,
  onShowJsonChange,
}: OriginalTabProps) {
  const pages = pagesTextResult?.pages ?? []
  const isPdfPreview = previewResult?.kind === 'pdf'
  // 페이지를 넘길 때마다 iframe 이 새로 만들어지므로, PDF 는 한 번만 받아 blob URL 로 띄운다.
  const pdfBlob = usePdfBlobUrl(isPdfPreview ? previewResult?.url : undefined)
  const isNativePdf = isPdfDoc
  const hasMultiplePages = new Set(pages.map((p) => p.page_number)).size > 1
  const maxPage = pages.length ? Math.max(...pages.map((p) => p.page_number)) : 1
  const clampedPage = Math.min(Math.max(originalPage, 1), maxPage)
  let iframeSrc: string | undefined
  if (previewResult?.url) {
    if (!isPdfPreview) iframeSrc = previewResult.url
    else if (pdfBlob.blobUrl) iframeSrc = `${pdfBlob.blobUrl}#page=${clampedPage}`
    // blob 로 받지 못했을 때만 원격 URL 로 폴백한다. 받는 중에는 undefined → 로딩 표시.
    else if (pdfBlob.isError) iframeSrc = `${previewResult.url}#page=${clampedPage}`
  }
  const currentPageText = isNativePdf && hasMultiplePages
    ? pages.filter((p) => p.page_number === clampedPage).map((p) => p.text).join('\n\n')
    : null

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', gap: 'var(--space-2)' }}>
      {hasMultiplePages && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
          <button
            className="ds-btn ds-btn--secondary ds-btn--sm"
            disabled={clampedPage <= 1}
            onClick={() => onOriginalPageChange(clampedPage - 1)}
            style={{ cursor: 'pointer' }}
          >
            ◀ 이전
          </button>
          <span style={{ fontSize: 13 }}>
            {clampedPage} / {maxPage} 쪽
          </span>
          <button
            className="ds-btn ds-btn--secondary ds-btn--sm"
            disabled={clampedPage >= maxPage}
            onClick={() => onOriginalPageChange(clampedPage + 1)}
            style={{ cursor: 'pointer' }}
          >
            다음 ▶
          </button>
          <span style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
            {isNativePdf
              ? '원본과 파싱 텍스트가 같은 쪽으로 함께 이동합니다'
              : '원본 미리보기만 페이지 이동합니다 (텍스트는 문서 전체가 표시됩니다)'}
          </span>
        </div>
      )}
      {previewResult?.approximate && (
        <p style={{ fontSize: 12, color: 'var(--color-warning)', margin: 0, flexShrink: 0 }}>
          이 형식은 원본을 직접 렌더링할 수 없어 재구성한 근사치입니다 — 레이아웃·글꼴·이미지 배치가 실제 원본과 다를 수 있습니다. 정확한 원본은 "원본 다운로드"를 이용하세요.
        </p>
      )}
      <div style={{ flex: 1, minHeight: 0, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 'var(--space-4)' }}>
        <div style={{ minHeight: 0, display: 'flex', flexDirection: 'column' }}>
          <p style={{ fontSize: 12, color: 'var(--color-text-muted)', margin: '0 0 var(--space-2)', flexShrink: 0 }}>
            {isPdfPreview ? '원본 PDF' : '원본 (변환 미리보기)'}
          </p>
          {isPreviewError && (
            <p><ErrorText error={previewError} message="원문 미리보기를 만들지 못했습니다." /></p>
          )}
          {!isPreviewError && iframeSrc ? (
            <iframe
              key={isPdfPreview ? clampedPage : 'html'}
              src={iframeSrc}
              title="원본 문서"
              style={{ flex: 1, width: '100%', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-sm)', background: 'var(--color-surface)' }}
            />
          ) : !isPreviewError && (
            <div
              role="status"
              aria-label="원문 불러오는 중"
              style={{ display: 'flex', justifyContent: 'center', padding: 'var(--space-6)' }}
            >
              <Loader2 size={20} style={{ animation: 'spin 1s linear infinite', color: 'var(--color-text-muted)' }} />
            </div>
          )}
        </div>
        <div style={{ minHeight: 0, display: 'flex', flexDirection: 'column' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexShrink: 0 }}>
            <p style={{ fontSize: 12, color: 'var(--color-text-muted)', margin: '0 0 var(--space-2)' }}>
              파싱된 텍스트 (RAG 저장 형태){isNativePdf && hasMultiplePages ? ` (${clampedPage}쪽)` : ''}
            </p>
            <ViewModeToggle showJson={showJson} onChange={onShowJsonChange} />
          </div>
          <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-sm)', padding: 'var(--space-3)', background: showJson ? 'var(--color-surface-subtle)' : 'var(--color-surface)' }}>
            {isContentLoading && (
              <div style={{ display: 'flex', justifyContent: 'center', padding: 'var(--space-6)' }}>
                <Loader2 size={20} style={{ animation: 'spin 1s linear infinite', color: 'var(--color-text-muted)' }} />
              </div>
            )}
            {!isContentLoading && showJson && (
              <pre style={{
                fontSize: 12, lineHeight: 1.6, whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                fontFamily: 'var(--font-mono)', margin: 0,
              }}>
                {toBlocksJson(currentPageText ?? content?.full_text ?? '')}
              </pre>
            )}
            {!isContentLoading && !showJson && (
              <div className="markdown-body" style={{ fontSize: 13, lineHeight: 1.7 }}>
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {currentPageText ?? content?.full_text ?? ''}
                </ReactMarkdown>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
