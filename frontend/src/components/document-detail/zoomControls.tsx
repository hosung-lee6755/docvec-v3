import { Maximize2, MoveHorizontal, ZoomIn, ZoomOut } from 'lucide-react'
import type { ViewZoom } from './zoomState'

// 원문 대조의 원본 PDF 와 파싱된 텍스트가 함께 쓰는 배율 도구(2026-11-27). 상태와 저장은 zoomState.ts 에 있다

interface ZoomToolbarProps {
  label: string
  zoom: ViewZoom
  effectiveScale: number | null
  onChoose: (zoom: ViewZoom) => void
  onStep: (direction: 1 | -1) => void
}

export function ZoomToolbar({ label, zoom, effectiveScale, onChoose, onStep }: ZoomToolbarProps) {
  const zoomLabel = effectiveScale === null ? '—' : `${Math.round(effectiveScale * 100)}%`
  return (
    <div role="toolbar" aria-label={label} style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '4px 8px', borderBottom: '1px solid var(--color-border)', background: 'var(--color-surface)', flexShrink: 0 }}>
      <button type="button" className="ds-btn ds-btn--secondary ds-btn--sm" aria-label="축소" title="축소" onClick={() => onStep(-1)}>
        <ZoomOut size={14} aria-hidden="true" />
      </button>
      <span role="status" aria-label="배율" style={{ minWidth: 48, textAlign: 'center', fontSize: 12, fontVariantNumeric: 'tabular-nums' }}>
        {zoomLabel}
      </span>
      <button type="button" className="ds-btn ds-btn--secondary ds-btn--sm" aria-label="확대" title="확대" onClick={() => onStep(1)}>
        <ZoomIn size={14} aria-hidden="true" />
      </button>
      <span aria-hidden="true" style={{ width: 1, height: 18, background: 'var(--color-border)', margin: '0 4px' }} />
      <button type="button" className="ds-btn ds-btn--secondary ds-btn--sm" aria-label="폭 맞춤" title="폭 맞춤"
        aria-pressed={zoom === 'fit-width'} onClick={() => onChoose('fit-width')}
        style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
        <MoveHorizontal size={14} aria-hidden="true" />폭
      </button>
      <button type="button" className="ds-btn ds-btn--secondary ds-btn--sm" aria-label="쪽 맞춤" title="쪽 맞춤"
        aria-pressed={zoom === 'fit-page'} onClick={() => onChoose('fit-page')}
        style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
        <Maximize2 size={14} aria-hidden="true" />쪽
      </button>
    </div>
  )
}
