// 좌표가 저장되지 않은 블록(API/시드로 만든 워크플로우의 position === {})이 편집기에서 한 점(0,0)에
// 겹쳐 보이지 않도록 하는 대체 배치. 블록 카드의 연결 핸들이 위(입력)·아래(출력)에 있어 위에서 아래로
// 흐르는 배치가 자연스럽다 — 한 열에 LAYOUT_ROWS개씩 아래로 쌓고 다음 열로 넘어간다.
// 간격은 카드 크기(약 287×68)보다 넓게 잡아 서로 겹치지 않게 한다. 마이그레이션
// `3c5e7a9b1d2f_layout_blocks_without_position.py` 와 같은 규칙이어야 한다.
export const LAYOUT_ROWS = 6
export const LAYOUT_X_GAP = 360
export const LAYOUT_Y_GAP = 130

export interface BlockPosition {
  x: number
  y: number
}

export function hasPosition(position: unknown): position is BlockPosition {
  if (typeof position !== 'object' || position === null) return false
  const { x, y } = position as { x?: unknown; y?: unknown }
  return typeof x === 'number' && typeof y === 'number'
}

export function fallbackPosition(index: number): BlockPosition {
  const column = Math.floor(index / LAYOUT_ROWS)
  const row = index % LAYOUT_ROWS
  return { x: column * LAYOUT_X_GAP, y: row * LAYOUT_Y_GAP }
}
