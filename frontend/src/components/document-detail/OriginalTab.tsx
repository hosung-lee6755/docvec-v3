import { useState } from 'react'
import { ArrowLeft, Loader2 } from 'lucide-react'
import { PdfPageViewer } from './PdfPageViewer'
import { ZoomableTextPane } from './ZoomableTextPane'
import ReactMarkdown, { type Components } from 'react-markdown'
import { markdownPlugins } from '../../lib/markdownPlugins'
import { MarkdownLink } from './MarkdownLink'
import { usePdfBlobUrl } from '../../hooks/usePdfBlobUrl'
import { ViewModeToggle } from './documentDetailParts'
import { legacyTablesToMarkdown, toRagRecordsJson, type RagRecordSource } from './documentDetailHelpers'
import type { DocumentChunksResult, DocumentTable } from '../../hooks/useDocuments'
import { splitByTables } from '../../lib/tableSpans'
import { SpanTable } from './SpanTable'
import { closeSplitTables, isEmptyTableHead } from './pageTableFragments'
import { ErrorText } from '../ui'

// 쪽 조각의 이어진 표에 붙인 빈 머리 행(closeSplitTables)은 그리지 않는다
const PAGE_MARKDOWN_COMPONENTS: Components = {
  a: MarkdownLink,
  thead: ({ node, ...props }) => (isEmptyTableHead(node) ? null : <thead {...props} />),
}

interface Page {
  page_number: number
  text: string
  start?: number
  end?: number
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
  ragSource: RagRecordSource
  chunksResult: DocumentChunksResult | undefined
  pagesTextResult: { pages: Page[]; total_pages?: number; synced?: boolean } | undefined
  previewResult: PreviewResult | undefined
  isPdfDoc: boolean
  originalPage: number
  showJson: boolean
  onOriginalPageChange: (page: number) => void
  onShowJsonChange: (v: boolean) => void
  // 저장된 표(합친 칸 목록 포함). 본문의 같은 표를 칸을 합친 모양으로 그린다
  tables?: DocumentTable[]
  // 다른 탭에서 넘어왔을 때 그 탭 이름과 돌아가기 동작
  returnLabel?: string
  onReturn?: () => void
}

export default function OriginalTab({
  isContentLoading,
  isPreviewError,
  previewError,
  content,
  ragSource,
  chunksResult,
  pagesTextResult,
  previewResult,
  isPdfDoc,
  originalPage,
  showJson,
  onOriginalPageChange,
  onShowJsonChange,
  returnLabel,
  onReturn,
  tables,
}: OriginalTabProps) {
  const pages = pagesTextResult?.pages ?? []
  const isPdfPreview = previewResult?.kind === 'pdf'
  // 페이지를 넘길 때마다 iframe 이 새로 만들어지므로, PDF 는 한 번만 받아 blob URL 로 띄운다.
  const pdfBlob = usePdfBlobUrl(isPdfPreview ? previewResult?.url : undefined)
  // PDF.js 로 열지 못한 PDF 의 blob URL. 그 문서만 예전처럼 브라우저 PDF 뷰어로 보여 준다
  const [viewerFailedUrl, setViewerFailedUrl] = useState<string | undefined>(undefined)
  const viewerUrl = isPdfPreview && pdfBlob.blobUrl && viewerFailedUrl !== pdfBlob.blobUrl ? pdfBlob.blobUrl : undefined
  const isNativePdf = isPdfDoc
  // 원본 PDF 는 page_map 으로, HWP·DOCX 는 미리보기 PDF 쪽에 맞춰 자른 파싱 본문이 온다(synced).
  // 예전에는 원본 PDF 만 함께 넘겼고, 글이 없는 마지막 쪽(그림·빈 쪽)으로는 넘어가지 못했다
  const isPageSynced = (isNativePdf || isPdfPreview) && (pagesTextResult?.synced ?? isNativePdf)
  const lastTextPage = pages.length ? Math.max(...pages.map((p) => p.page_number)) : 1
  const maxPage = Math.max(pagesTextResult?.total_pages ?? 0, lastTextPage, 1)
  const hasMultiplePages = maxPage > 1
  const clampedPage = Math.min(Math.max(originalPage, 1), maxPage)
  let iframeSrc: string | undefined
  if (previewResult?.url) {
    if (!isPdfPreview) iframeSrc = previewResult.url
    else if (pdfBlob.blobUrl) iframeSrc = `${pdfBlob.blobUrl}#page=${clampedPage}`
    // blob 로 받지 못했을 때만 원격 URL 로 폴백한다. 받는 중에는 undefined → 로딩 표시.
    else if (pdfBlob.isError) iframeSrc = `${previewResult.url}#page=${clampedPage}`
  }
  const currentPageText = isPageSynced && hasMultiplePages
    ? pages.filter((p) => p.page_number === clampedPage).map((p) => p.text).join('\n\n')
    : null
  const isCurrentPageEmpty = currentPageText !== null && !currentPageText.trim()
  // JSON 보기도 텍스트 보기와 같은 쪽 구간의 청크를 보인다. 예전에는 원본 PDF 만, 그것도 청크의 시작 쪽으로만 걸러
  // HWP·DOCX 는 쪽을 넘겨도 문서 전체 청크가 그대로였다(2026-11-26)
  // 글이 없는 쪽(pages 에 없음)은 빈 구간으로 보아 청크를 보이지 않는다
  const currentPage = pages.find((p) => p.page_number === clampedPage)
  const pageSpan = currentPage ? { start: currentPage.start, end: currentPage.end } : { start: 0, end: 0 }
  const jsonScope = isPageSynced && hasMultiplePages ? { page_number: clampedPage, ...pageSpan } : undefined

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', gap: 'var(--space-2)' }}>
      {onReturn && (
        <div style={{ flexShrink: 0 }}>
          <button type="button" className="ds-btn ds-btn--secondary ds-btn--sm" onClick={onReturn}
            style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
            <ArrowLeft size={12} aria-hidden="true" />
            {returnLabel ? `${returnLabel} 탭으로 돌아가기` : '이전 탭으로 돌아가기'}
          </button>
        </div>
      )}
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
            {!isPageSynced
              ? '원본 미리보기만 페이지 이동합니다 (텍스트는 문서 전체가 표시됩니다)'
              : isNativePdf
                ? '원본과 파싱 텍스트가 같은 쪽으로 함께 이동합니다'
                : '미리보기와 파싱 텍스트가 같은 쪽으로 함께 이동합니다 (미리보기 쪽 나눔에 맞춰 나눈 글입니다)'}
          </span>
        </div>
      )}
      {previewResult?.approximate && (
        <p style={{ fontSize: 12, color: 'var(--color-warning)', margin: 0, flexShrink: 0 }}>
          이 형식은 원본을 직접 렌더링할 수 없어 재구성한 근사치입니다 — 레이아웃·글꼴·이미지 배치가 실제 원본과 다를 수 있습니다. 정확한 원본은 "원본 다운로드"를 이용하세요.
        </p>
      )}
      <div style={{ flex: 1, minHeight: 0, display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: 'var(--space-4)' }}>
        <div style={{ minHeight: 0, display: 'flex', flexDirection: 'column' }}>
          <p style={{ fontSize: 12, color: 'var(--color-text-muted)', margin: '0 0 var(--space-2)', flexShrink: 0 }}>
            {isPdfPreview ? '원본 PDF' : '원본 (변환 미리보기)'}
          </p>
          {isPreviewError && (
            <p><ErrorText error={previewError} message="원문 미리보기를 만들지 못했습니다." /></p>
          )}
          {!isPreviewError && viewerUrl ? (
            <PdfPageViewer url={viewerUrl} page={clampedPage} onLoadError={() => setViewerFailedUrl(viewerUrl)} />
          ) : !isPreviewError && iframeSrc ? (
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
              파싱된 텍스트 (RAG 저장 형태){isPageSynced && hasMultiplePages ? ` (${clampedPage}쪽)` : ''}
            </p>
            <ViewModeToggle showJson={showJson} onChange={onShowJsonChange} />
          </div>
          <ZoomableTextPane
            contentKey={`${clampedPage}|${showJson}|${isContentLoading}|${chunksResult ? 'chunks' : ''}|${content?.full_text.length ?? 0}`}
            background={showJson ? 'var(--color-surface-subtle)' : 'var(--color-surface)'}
          >
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
                {chunksResult
                  ? toRagRecordsJson(ragSource, chunksResult.chunks, jsonScope)
                  : '저장된 청크를 불러오는 중입니다.'}
              </pre>
            )}
            {!isContentLoading && !showJson && isCurrentPageEmpty && (
              <p style={{ fontSize: 13, color: 'var(--color-text-muted)', margin: 0 }}>
                이 쪽에서 추출된 글이 없습니다. 그림이나 빈 쪽일 수 있습니다.
              </p>
            )}
            {!isContentLoading && !showJson && !isCurrentPageEmpty && (
              <div className="markdown-body" style={{ fontSize: 13, lineHeight: 1.7 }}>
                {splitByTables(currentPageText ?? content?.full_text ?? '', tables).map((part, index) => (
                  part.kind === 'table'
                    ? <SpanTable key={index} table={part.table} label={part.table.title ?? undefined} />
                    : (
                      <ReactMarkdown key={index} remarkPlugins={markdownPlugins} components={PAGE_MARKDOWN_COMPONENTS}>
                        {legacyTablesToMarkdown(currentPageText === null ? part.text : closeSplitTables(part.text))}
                      </ReactMarkdown>
                    )
                ))}
              </div>
            )}
          </ZoomableTextPane>
        </div>
      </div>
    </div>
  )
}
