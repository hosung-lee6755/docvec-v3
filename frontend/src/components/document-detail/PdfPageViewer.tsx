import { useEffect, useRef, useState } from 'react'
import { Loader2 } from 'lucide-react'
import { loadPdfDocument, type PdfDocumentProxy, type PdfRenderTask } from './pdfjsLoader'
import { ZoomToolbar } from './zoomControls'
import { useStoredZoom, type ViewZoom } from './zoomState'

// 원문 대조의 원본 PDF 를 쪽 하나씩 그린다(2026-11-25). 예전에는 브라우저 PDF 뷰어를 iframe 으로 띄웠는데,
// 기본 배율을 브라우저가 쪽 크기에 따라 정해 문서마다 보이는 크기가 달랐고, 쪽을 넘길 때마다 iframe 을 새로
// 만들어 사용자가 바꾼 배율이 사라졌다. 이제 기본은 폭 맞춤이고, 사용자가 고른 배율은 다음 쪽과 다른 문서에도 남는다.
// 배율 도구는 파싱된 텍스트 영역과 같은 것을 쓴다(zoomControls, 2026-11-27).

export type PdfZoom = ViewZoom

export const ZOOM_STORAGE_KEY = 'docvec.original-pdf-zoom'
// 캔버스 둘레 여백(px). 폭 맞춤 배율을 셀 때 뺀다
const PAGE_GUTTER = 16

interface PdfPageViewerProps {
  url: string
  page: number
  onLoadError?: () => void
}

export function PdfPageViewer({ url, page, onLoadError }: PdfPageViewerProps) {
  const { zoom, chooseZoom, stepZoom } = useStoredZoom(ZOOM_STORAGE_KEY)
  const [pdf, setPdf] = useState<PdfDocumentProxy | null>(null)
  const [effectiveScale, setEffectiveScale] = useState<number | null>(null)
  const [frame, setFrame] = useState({ width: 0, height: 0 })
  const scrollRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const onLoadErrorRef = useRef(onLoadError)

  useEffect(() => {
    onLoadErrorRef.current = onLoadError
  }, [onLoadError])

  useEffect(() => {
    let cancelled = false
    let loaded: PdfDocumentProxy | null = null
    setPdf(null)
    loadPdfDocument(url)
      .then((document) => {
        loaded = document
        if (cancelled) void document.destroy()
        else setPdf(document)
      })
      .catch(() => {
        if (!cancelled) onLoadErrorRef.current?.()
      })
    return () => {
      cancelled = true
      if (loaded) void loaded.destroy()
    }
  }, [url])

  // 보이는 영역 크기. 폭·쪽 맞춤 배율을 정하고, 창 크기가 바뀌면 다시 맞춘다
  useEffect(() => {
    const element = scrollRef.current
    if (!element) return undefined
    const measure = () => setFrame({ width: element.clientWidth, height: element.clientHeight })
    measure()
    if (typeof ResizeObserver === 'undefined') return undefined
    const observer = new ResizeObserver(measure)
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    if (!pdf) return undefined
    let cancelled = false
    let task: PdfRenderTask | null = null
    const pageNumber = Math.min(Math.max(page, 1), pdf.numPages)
    pdf.getPage(pageNumber).then((pdfPage) => {
      if (cancelled) return
      const base = pdfPage.getViewport({ scale: 1 })
      const usableWidth = Math.max(frame.width - PAGE_GUTTER * 2, 100)
      const usableHeight = Math.max(frame.height - PAGE_GUTTER * 2, 100)
      const scale = zoom === 'fit-width'
        ? usableWidth / base.width
        : zoom === 'fit-page'
          ? Math.min(usableWidth / base.width, usableHeight / base.height)
          : zoom
      setEffectiveScale(scale)
      const canvas = canvasRef.current
      const context = canvas?.getContext('2d')
      if (!canvas || !context) return
      const pixelRatio = window.devicePixelRatio || 1
      const viewport = pdfPage.getViewport({ scale: scale * pixelRatio })
      canvas.width = Math.floor(viewport.width)
      canvas.height = Math.floor(viewport.height)
      canvas.style.width = `${Math.floor(viewport.width / pixelRatio)}px`
      canvas.style.height = `${Math.floor(viewport.height / pixelRatio)}px`
      task = pdfPage.render({ canvasContext: context, viewport })
      task.promise.catch(() => {
        // 다음 쪽이나 배율로 바뀌어 취소된 그리기다
      })
    }).catch(() => {
      if (!cancelled) onLoadErrorRef.current?.()
    })
    return () => {
      cancelled = true
      task?.cancel()
    }
  }, [pdf, page, zoom, frame.width, frame.height])

  // 쪽을 넘기면 새 쪽의 처음부터 보여 준다
  useEffect(() => {
    scrollRef.current?.scrollTo?.({ top: 0, left: 0 })
  }, [page])

  return (
    <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-sm)', overflow: 'hidden' }}>
      <ZoomToolbar label="원본 배율" zoom={zoom} effectiveScale={effectiveScale}
        onChoose={chooseZoom} onStep={(direction) => stepZoom(effectiveScale, direction)} />
      <div ref={scrollRef} data-testid="pdf-page-scroll"
        style={{ flex: 1, minHeight: 0, overflow: 'auto', background: 'var(--color-surface-subtle)', padding: PAGE_GUTTER, textAlign: 'center' }}>
        {!pdf && (
          <div role="status" aria-label="원본 불러오는 중" style={{ display: 'flex', justifyContent: 'center', padding: 'var(--space-6)' }}>
            <Loader2 size={20} style={{ animation: 'spin 1s linear infinite', color: 'var(--color-text-muted)' }} />
          </div>
        )}
        <canvas ref={canvasRef} aria-label={`원본 ${page}쪽`}
          style={{ display: pdf ? 'inline-block' : 'none', boxShadow: '0 1px 4px rgba(0,0,0,0.18)', background: '#fff' }} />
      </div>
    </div>
  )
}
