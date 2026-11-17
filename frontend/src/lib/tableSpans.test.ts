import { describe, expect, it } from 'vitest'
import { layoutCells } from './tableSpans'

const texts = (cells: { text: string }[][]) => cells.map((row) => row.map((cell) => cell.text))

describe('layoutCells', () => {
  it('returns every cell unchanged when there are no spans', () => {
    const cells = layoutCells([['a', 'b'], ['c', 'd']], null)

    expect(texts(cells)).toEqual([['a', 'b'], ['c', 'd']])
    expect(cells.flat().every((cell) => cell.rowSpan === 1 && cell.colSpan === 1)).toBe(true)
  })

  it('hides the repeated cells under a vertical merge', () => {
    const rows = [['구분', '값'], ['합계', '1'], ['합계', '2']]

    const cells = layoutCells(rows, [{ row: 1, col: 0, row_span: 2, col_span: 1 }])

    expect(texts(cells)).toEqual([['구분', '값'], ['합계', '1'], ['2']])
    expect(cells[1][0]).toMatchObject({ rowSpan: 2, colSpan: 1 })
    expect(cells[2][0].column).toBe(1)
  })

  it('stretches a horizontal merge over its empty neighbours', () => {
    const cells = layoutCells([['지원 조건', '', ''], ['기간', '한도', '비율']], [
      { row: 0, col: 0, row_span: 1, col_span: 3 },
    ])

    expect(texts(cells)).toEqual([['지원 조건'], ['기간', '한도', '비율']])
    expect(cells[0][0].colSpan).toBe(3)
  })

  it('clamps a span that runs past the table and ignores one outside it', () => {
    const cells = layoutCells([['a', 'b']], [
      { row: 0, col: 0, row_span: 5, col_span: 5 },
      { row: 9, col: 0, row_span: 2, col_span: 1 },
    ])

    expect(cells).toEqual([[{ text: 'a', column: 0, rowSpan: 1, colSpan: 2 }]])
  })
})
