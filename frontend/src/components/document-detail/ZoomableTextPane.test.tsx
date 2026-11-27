import { describe, it, expect, beforeEach } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { TEXT_ZOOM_STORAGE_KEY, ZoomableTextPane } from './ZoomableTextPane'
import { ZOOM_STORAGE_KEY } from './PdfPageViewer'

function pane(key = 'p1') {
  return (
    <ZoomableTextPane contentKey={key} background="white">
      <p>제11조(요양보상) ① 임직원이 업무상 입은 부상 또는 질병으로 …</p>
    </ZoomableTextPane>
  )
}

describe('ZoomableTextPane', () => {
  beforeEach(() => window.localStorage.clear())

  it('offers the same zoom tools as the original PDF and starts fitted to the width', () => {
    // 2026-11-27: 원본 PDF 에만 배율 도구가 있어 파싱된 텍스트는 글자 크기를 바꿀 수 없었다
    render(pane())

    for (const name of ['축소', '확대', '폭 맞춤', '쪽 맞춤']) {
      expect(screen.getByRole('button', { name })).toBeInTheDocument()
    }
    expect(screen.getByRole('button', { name: '폭 맞춤' }).getAttribute('aria-pressed')).toBe('true')
    expect(screen.getByRole('status', { name: '배율' }).textContent).toBe('100%')
  })

  it('zooms the text and keeps the choice apart from the original PDF zoom', () => {
    const { unmount } = render(pane())

    fireEvent.click(screen.getByRole('button', { name: '확대' }))

    expect(screen.getByRole('status', { name: '배율' }).textContent).toBe('110%')
    expect(window.localStorage.getItem(TEXT_ZOOM_STORAGE_KEY)).toBe('1.1')
    expect(window.localStorage.getItem(ZOOM_STORAGE_KEY)).toBeNull()

    unmount()
    render(pane('p2'))
    expect(screen.getByRole('status', { name: '배율' }).textContent).toBe('110%')
  })

  it('switches to fitting the page when asked', () => {
    render(pane())

    fireEvent.click(screen.getByRole('button', { name: '쪽 맞춤' }))

    expect(screen.getByRole('button', { name: '쪽 맞춤' }).getAttribute('aria-pressed')).toBe('true')
    expect(window.localStorage.getItem(TEXT_ZOOM_STORAGE_KEY)).toBe('fit-page')
  })
})
