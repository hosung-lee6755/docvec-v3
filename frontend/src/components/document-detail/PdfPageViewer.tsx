import { useEffect, useRef, useState } from 'react'
import { Loader2, Maximize2, MoveHorizontal, ZoomIn, ZoomOut } from 'lucide-react'
import { loadPdfDocument, type PdfDocumentProxy, type PdfRenderTask } from './pdfjsLoader'

// 원문 대조의 원본 PDF 를 쪽 하나씩 그린다(2026-11-25). 예전에는 브라우저 PDF 뷰어를 iframe 으로 띄웠는데,
// 기본 배율을 브라우저가 쪽 크기에 따라 정해 문서마다 보이는 크기가 달랐고, 쪽을 넘길 때마다 iframe 을 새로
// 만들어 사용자가 바꾼 배율이 사라졌다. 이제 기본은 폭 맞춤이고, 사용자가 고른 배율은 다음 쪽과 다른 문서에도 남는다.

export type PdfZoom = 'fit-width' | 'fit-page' | number

export const ZOOM_STORAGE_KEY = 'docvec.original-pdf-zoom'
const ZOOM_STEPS = [0.5, 0.67, 0.75, 0.9, 1, 1.1, 1.25, 1.5, 1.75, 2, 2.5, 3]
// 캔버스 둘레 여백(px). 폭 맞춤 배율을 셀 때 뺀다
const PAGE_GUTTER = 16

function readStoredZoom(): PdfZoom {
  try {
    const raw = window.localStorage.getItem(ZOOM_STORAGE_KEY)
    if (raw === 'fit-width' || raw === 'fit-page') return raw
    const value = raw === null ? NaN : Number(raw)
    return Number.isFinite(value) && value > 0 ? value : 'fit-width'
  } catch {
    return 'fit-width'
  }
}

function storeZoom(zoom: PdfZoom): void {
  try {
    window.localStorage.setItem(ZOOM_STORAGE_KEY, String(zoom))
  } catch {
    // 저장소를 쓸 수 없으면(개인 정보 보호 모드 등) 이번 화면에서만 배율을 쓴다
  }
}

function nextZoomStep(current: number, direction: 1 | -1): number {
  if (direction > 0) return ZOOM_STEPS.find((step) => step > current + 0.001) ?? ZOOM_STEPS[ZOOM_STEPS.length - 1]
  return [...ZOOM_STEPS].reverse().find((step) => step < current - 0.001) ?? ZOOM_STEPS[0]
}

interface PdfPageViewerProps {
  url: string
  page: number
  onLoadError?: () => void
}

export function PdfPageViewer({ url, page, onLoadError }: PdfPageViewerProps) {
  const [zoom, setZoom] = useState<PdfZoom>(readStoredZoom)
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

  const chooseZoom = (next: PdfZoom) => {
    setZoom(next)
    storeZoom(next)
  }
  const stepZoom = (direction: 1 | -1) => {
    const current = typeof zoom === 'number' ? zoom : effectiveScale ?? 1
    chooseZoom(nextZoomStep(current, direction))
  }
  const zoomLabel = effectiveScale === null ? '—' : `${Math.round(effectiveScale * 100)}%`

  return (
    <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-sm)', overflow: 'hidden' }}>
      <div role="toolbar" aria-label="원본 배율" style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '4px 8px', borderBottom: '1px solid var(--color-border)', background: 'var(--color-surface)', flexShrink: 0 }}>
        <button type="button" className="ds-btn ds-btn--secondary ds-btn--sm" aria-label="축소" title="축소" onClick={() => stepZoom(-1)}>
          <ZoomOut size={14} aria-hidden="true" />
        </button>
        <span role="status" aria-label="배율" style={{ minWidth: 48, textAlign: 'center', fontSize: 12, fontVariantNumeric: 'tabular-nums' }}>
          {zoomLabel}
        </span>
        <button type="button" className="ds-btn ds-btn--secondary ds-btn--sm" aria-label="확대" title="확대" onClick={() => stepZoom(1)}>
          <ZoomIn size={14} aria-hidden="true" />
        </button>
        <span aria-hidden="true" style={{ width: 1, height: 18, background: 'var(--color-border)', margin: '0 4px' }} />
        <button type="button" className="ds-btn ds-btn--secondary ds-btn--sm" aria-label="폭 맞춤" title="폭 맞춤"
          aria-pressed={zoom === 'fit-width'} onClick={() => chooseZoom('fit-width')}
          style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
          <MoveHorizontal size={14} aria-hidden="true" />폭
        </button>
        <button type="button" className="ds-btn ds-btn--secondary ds-btn--sm" aria-label="쪽 맞춤" title="쪽 맞춤"
          aria-pressed={zoom === 'fit-page'} onClick={() => chooseZoom('fit-page')}
          style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
          <Maximize2 size={14} aria-hidden="true" />쪽
        </button>
      </div>
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
