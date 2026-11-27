import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { ZoomToolbar } from './zoomControls'
import { useStoredZoom } from './zoomState'

// 원문 대조의 "파싱된 텍스트" 영역. 원본 PDF 와 같은 배율 도구를 둔다(2026-11-27).
// - 축소·확대: 글과 표를 함께 키우고 줄인다(CSS zoom)
// - 폭 맞춤(기본): 글은 영역 폭에서 줄을 바꾸고, 영역보다 넓은 표가 있으면 다 보이게 줄인다
// - 쪽 맞춤: 지금 쪽의 글 전체가 스크롤 없이 들어오게 줄인다(최소 50%)
// 배율은 원본 PDF 와 따로 저장한다.

export const TEXT_ZOOM_STORAGE_KEY = 'docvec.parsed-text-zoom'
const MIN_FIT_SCALE = 0.5
const MAX_FIT_PASSES = 12

interface ZoomableTextPaneProps {
  // 보이는 글이 바뀌면(쪽 이동, JSON 보기, 불러오기 끝) 맞춤 배율을 다시 잰다
  contentKey: string
  background: string
  children: ReactNode
}

function overflowsWidth(box: HTMLElement): boolean {
  return box.scrollWidth > box.clientWidth + 1
}

function overflowsHeight(box: HTMLElement): boolean {
  return box.scrollHeight > box.clientHeight + 1
}

export function ZoomableTextPane({ contentKey, background, children }: ZoomableTextPaneProps) {
  const { zoom, chooseZoom, stepZoom } = useStoredZoom(TEXT_ZOOM_STORAGE_KEY)
  const [effectiveScale, setEffectiveScale] = useState<number | null>(null)
  const [frame, setFrame] = useState({ width: 0, height: 0 })
  const boxRef = useRef<HTMLDivElement>(null)
  const contentRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const element = boxRef.current
    if (!element) return undefined
    const measure = () => setFrame({ width: element.clientWidth, height: element.clientHeight })
    measure()
    if (typeof ResizeObserver === 'undefined') return undefined
    const observer = new ResizeObserver(measure)
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  // 배율을 글에 입히고, 맞춤이면 넘치지 않을 때까지 줄여 가며 잰다(그리기 전에 끝내 깜빡이지 않게 한다)
  useLayoutEffect(() => {
    const box = boxRef.current
    const content = contentRef.current
    if (!box || !content) return
    const apply = (scale: number) => {
      content.style.zoom = String(scale)
    }
    if (typeof zoom === 'number') {
      apply(zoom)
      setEffectiveScale(zoom)
      return
    }
    let scale = 1
    apply(scale)
    for (let pass = 0; pass < MAX_FIT_PASSES && scale > MIN_FIT_SCALE && overflowsWidth(box); pass++) {
      scale = Math.max(MIN_FIT_SCALE, scale * (box.clientWidth / box.scrollWidth))
      apply(scale)
    }
    if (zoom === 'fit-page') {
      // 줄이면 한 줄에 글자가 더 들어가 높이는 배율의 제곱쯤으로 준다. 제곱근만큼 줄이고 남으면 조금씩 더 줄인다
      for (let pass = 0; pass < MAX_FIT_PASSES && scale > MIN_FIT_SCALE && overflowsHeight(box); pass++) {
        const ratio = Math.sqrt(box.clientHeight / box.scrollHeight)
        scale = Math.max(MIN_FIT_SCALE, scale * Math.min(ratio, 0.97))
        apply(scale)
      }
    }
    setEffectiveScale(scale)
  }, [zoom, contentKey, frame.width, frame.height])

  return (
    <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-sm)', overflow: 'hidden' }}>
      <ZoomToolbar label="파싱된 텍스트 배율" zoom={zoom} effectiveScale={effectiveScale}
        onChoose={chooseZoom} onStep={(direction) => stepZoom(effectiveScale, direction)} />
      <div ref={boxRef} data-testid="parsed-text-scroll"
        style={{ flex: 1, minHeight: 0, overflowY: 'auto', overflowX: 'auto', overflowWrap: 'anywhere', padding: 'var(--space-3)', background }}>
        <div ref={contentRef}>{children}</div>
      </div>
    </div>
  )
}
