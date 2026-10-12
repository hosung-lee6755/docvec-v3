import { describe, expect, it } from 'vitest'
import { fallbackPosition, hasPosition, LAYOUT_ROWS, LAYOUT_X_GAP, LAYOUT_Y_GAP } from './workflowLayout'

describe('hasPosition', () => {
  it('accepts numeric x/y', () => {
    expect(hasPosition({ x: 0, y: 0 })).toBe(true)
    expect(hasPosition({ x: 240, y: -10 })).toBe(true)
  })

  it('rejects empty or partial position objects', () => {
    expect(hasPosition({})).toBe(false)
    expect(hasPosition({ x: 10 } as never)).toBe(false)
    expect(hasPosition({ x: '1', y: '2' } as never)).toBe(false)
    expect(hasPosition(undefined as never)).toBe(false)
  })
})

describe('fallbackPosition', () => {
  it('stacks blocks top to bottom in the first column (handles are top=input, bottom=output)', () => {
    expect(fallbackPosition(0)).toEqual({ x: 0, y: 0 })
    expect(fallbackPosition(1)).toEqual({ x: 0, y: LAYOUT_Y_GAP })
  })

  it('moves to the next column after LAYOUT_ROWS blocks and restarts at the top', () => {
    const lastOfFirstColumn = fallbackPosition(LAYOUT_ROWS - 1)
    const firstOfSecondColumn = fallbackPosition(LAYOUT_ROWS)

    expect(lastOfFirstColumn).toEqual({ x: 0, y: (LAYOUT_ROWS - 1) * LAYOUT_Y_GAP })
    expect(firstOfSecondColumn).toEqual({ x: LAYOUT_X_GAP, y: 0 })
  })

  it('keeps blocks far enough apart not to overlap (card is about 287x68)', () => {
    expect(LAYOUT_X_GAP).toBeGreaterThan(287)
    expect(LAYOUT_Y_GAP).toBeGreaterThan(68)
  })

  it('never returns the same coordinates for different indexes', () => {
    const seen = new Set<string>()
    for (let i = 0; i < 30; i += 1) {
      const { x, y } = fallbackPosition(i)
      seen.add(`${x},${y}`)
    }
    expect(seen.size).toBe(30)
  })
})
