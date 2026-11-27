import { useState } from 'react'

// 원문 대조의 배율 상태(2026-11-27). 화면 부품은 zoomControls.tsx 에 있다

export type ViewZoom = 'fit-width' | 'fit-page' | number

const ZOOM_STEPS = [0.5, 0.67, 0.75, 0.9, 1, 1.1, 1.25, 1.5, 1.75, 2, 2.5, 3]

function readStoredZoom(storageKey: string): ViewZoom {
  try {
    const raw = window.localStorage.getItem(storageKey)
    if (raw === 'fit-width' || raw === 'fit-page') return raw
    const value = raw === null ? NaN : Number(raw)
    return Number.isFinite(value) && value > 0 ? value : 'fit-width'
  } catch {
    return 'fit-width'
  }
}

function storeZoom(storageKey: string, zoom: ViewZoom): void {
  try {
    window.localStorage.setItem(storageKey, String(zoom))
  } catch {
    // 저장소를 쓸 수 없으면(개인 정보 보호 모드 등) 이번 화면에서만 배율을 쓴다
  }
}

export function nextZoomStep(current: number, direction: 1 | -1): number {
  if (direction > 0) return ZOOM_STEPS.find((step) => step > current + 0.001) ?? ZOOM_STEPS[ZOOM_STEPS.length - 1]
  return [...ZOOM_STEPS].reverse().find((step) => step < current - 0.001) ?? ZOOM_STEPS[0]
}

/** 저장된 배율과 그것을 바꾸는 동작. effectiveScale 은 맞춤 배율을 실제로 셈한 값이다(확대·축소의 출발점). */
export function useStoredZoom(storageKey: string) {
  const [zoom, setZoom] = useState<ViewZoom>(() => readStoredZoom(storageKey))
  const chooseZoom = (next: ViewZoom) => {
    setZoom(next)
    storeZoom(storageKey, next)
  }
  const stepZoom = (effectiveScale: number | null, direction: 1 | -1) => {
    const current = typeof zoom === 'number' ? zoom : effectiveScale ?? 1
    chooseZoom(nextZoomStep(current, direction))
  }
  return { zoom, chooseZoom, stepZoom }
}
