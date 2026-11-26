import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { PdfPageViewer, ZOOM_STORAGE_KEY } from './PdfPageViewer'

const mocks = vi.hoisted(() => {
  const getPage = vi.fn(async (_n: number) => ({
    getViewport: ({ scale }: { scale: number }) => ({ width: 600 * scale, height: 800 * scale }),
    render: () => ({ promise: Promise.resolve(), cancel: () => {} }),
  }))
  return {
    getPage,
    loadPdfDocument: vi.fn(async (_url: string) => ({ numPages: 3, getPage, destroy: async () => {} })),
  }
})

vi.mock('./pdfjsLoader', () => ({ loadPdfDocument: mocks.loadPdfDocument }))

describe('PdfPageViewer', () => {
  beforeEach(() => {
    // jsdom 에는 canvas 가 없다. 그리기 대신 배율과 쪽 요청만 본다
    HTMLCanvasElement.prototype.getContext = vi.fn(() => null) as unknown as HTMLCanvasElement['getContext']
    window.localStorage.clear()
    mocks.getPage.mockClear()
    mocks.loadPdfDocument.mockClear()
  })

  it('opens every document fitted to the width so the size does not depend on the file', async () => {
    render(<PdfPageViewer url="blob:a" page={2} />)

    await waitFor(() => expect(mocks.getPage).toHaveBeenCalledWith(2))
    expect(screen.getByRole('button', { name: '폭 맞춤' }).getAttribute('aria-pressed')).toBe('true')
  })

  it('lets the user zoom and keeps the choice for the next page and the next document', async () => {
    const { rerender, unmount } = render(<PdfPageViewer url="blob:a" page={1} />)
    await waitFor(() => expect(mocks.getPage).toHaveBeenCalled())

    fireEvent.click(screen.getByRole('button', { name: '확대' }))
    await waitFor(() => expect(screen.getByRole('status', { name: '배율' }).textContent).toMatch(/%$/))
    const zoomed = screen.getByRole('status', { name: '배율' }).textContent

    rerender(<PdfPageViewer url="blob:a" page={2} />)
    await waitFor(() => expect(mocks.getPage).toHaveBeenCalledWith(2))
    expect(screen.getByRole('status', { name: '배율' }).textContent).toBe(zoomed)
    expect(window.localStorage.getItem(ZOOM_STORAGE_KEY)).not.toBeNull()

    unmount()
    render(<PdfPageViewer url="blob:b" page={1} />)
    await waitFor(() => expect(mocks.loadPdfDocument).toHaveBeenCalledWith('blob:b'))
    expect(screen.getByRole('status', { name: '배율' }).textContent).toBe(zoomed)
  })

  it('goes back to fitting the page when asked', async () => {
    render(<PdfPageViewer url="blob:a" page={1} />)
    await waitFor(() => expect(mocks.getPage).toHaveBeenCalled())

    fireEvent.click(screen.getByRole('button', { name: '쪽 맞춤' }))

    expect(screen.getByRole('button', { name: '쪽 맞춤' }).getAttribute('aria-pressed')).toBe('true')
    expect(screen.getByRole('button', { name: '폭 맞춤' }).getAttribute('aria-pressed')).toBe('false')
  })

  it('reports a document that cannot be opened so the tab can fall back', async () => {
    mocks.loadPdfDocument.mockRejectedValueOnce(new Error('broken'))
    const onLoadError = vi.fn()

    render(<PdfPageViewer url="blob:bad" page={1} onLoadError={onLoadError} />)

    await waitFor(() => expect(onLoadError).toHaveBeenCalled())
  })
})
