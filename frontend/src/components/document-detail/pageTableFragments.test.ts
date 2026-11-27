import { describe, expect, it } from 'vitest'
import { closeSplitTables, isEmptyTableHead } from './pageTableFragments'

describe('closeSplitTables', () => {
  it('gives table rows continued from the previous page an empty head so they render as a table', () => {
    const page = '| 부산 | 120 |\n| 인천 | 80 |\n\n다음 문단'

    expect(closeSplitTables(page)).toBe('|  |  |\n| --- | --- |\n| 부산 | 120 |\n| 인천 | 80 |\n\n다음 문단')
  })

  it('leaves complete tables alone', () => {
    const page = '[표 3]\n| 항구 | 물동량 |\n| --- | --- |\n| 부산 | 120 |\n'

    expect(closeSplitTables(page)).toBe(page)
  })

  it('closes a row cut at the end of the page and gives it an empty head', () => {
    const page = '앞 문단\n\n[표 37]\n| ※ 사업대상자 선정 우선순위 / ◦ 첫 항목 / '

    expect(closeSplitTables(page)).toBe('앞 문단\n\n[표 37]\n|  |\n| --- |\n| ※ 사업대상자 선정 우선순위 / ◦ 첫 항목 / |')
  })

  it('reopens a row cut at the start of the page', () => {
    const page = '· 둘째 쪽 항목 |\n|---|\n\n○ 구비서류'

    expect(closeSplitTables(page)).toBe('| · 둘째 쪽 항목 |\n|---|\n\n○ 구비서류')
  })

  it('puts the rest of a cell continued from the previous page back in its own column', () => {
    // 앞 쪽에서 넷째 칸 가운데가 잘렸으면 뒤 쪽 첫 조각은 넷째 칸 글이다. 첫 칸에 놓으면 열이 어긋난다
    const page = '야간 비율(D4) · 설정 기준값(공통) |\n| 3. 모델 | 32건 | 운영 분리 | 학습(D2) |'

    expect(closeSplitTables(page)).toBe(
      '|  |  |  |  |\n| --- | --- | --- | --- |\n|  |  |  | 야간 비율(D4) · 설정 기준값(공통) |\n| 3. 모델 | 32건 | 운영 분리 | 학습(D2) |',
    )
  })

  it('gives a page that starts at the divider row an empty head', () => {
    expect(closeSplitTables('|---|---|\n| a | b |')).toBe('|  |  |\n|---|---|\n| a | b |')
  })

  it('does not take a plain sentence with a bar for a table', () => {
    expect(closeSplitTables('A | B 는 선택이다')).toBe('A | B 는 선택이다')
  })
})

describe('isEmptyTableHead', () => {
  const cell = (text: string) => ({ type: 'element', tagName: 'th', children: text ? [{ type: 'text', value: text }] : [] })
  const head = (...cells: object[]) => ({ type: 'element', tagName: 'thead', children: [{ type: 'element', tagName: 'tr', children: cells }] })

  it('is true only when every head cell is blank', () => {
    expect(isEmptyTableHead(head(cell(''), cell(' ')))).toBe(true)
    expect(isEmptyTableHead(head(cell(''), cell('항구')))).toBe(false)
    expect(isEmptyTableHead(undefined)).toBe(false)
  })
})
