import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import OriginalTab from './OriginalTab'

vi.mock('../../hooks/usePdfBlobUrl', () => ({
  usePdfBlobUrl: () => ({ blobUrl: 'blob:pdf', isLoading: false, isError: false }),
}))
vi.mock('react-markdown', () => ({ default: ({ children }: { children: string }) => <div>{children}</div> }))
const pdfMocks = vi.hoisted(() => ({
  loadPdfDocument: vi.fn(async (_url: string) => ({
    numPages: 8,
    getPage: async () => ({
      getViewport: ({ scale }: { scale: number }) => ({ width: 600 * scale, height: 800 * scale }),
      render: () => ({ promise: Promise.resolve(), cancel: () => {} }),
    }),
    destroy: async () => {},
  })),
}))
vi.mock('./pdfjsLoader', () => ({ loadPdfDocument: pdfMocks.loadPdfDocument }))
HTMLCanvasElement.prototype.getContext = vi.fn(() => null) as unknown as HTMLCanvasElement['getContext']

const baseProps = {
  isContentLoading: false,
  isPreviewError: false,
  content: { full_text: '문서 전체 본문', chunk_count: 1 },
  ragSource: {} as never,
  chunksResult: undefined,
  previewResult: { kind: 'pdf' as const, url: 'https://minio/preview.pdf' },
  showJson: false,
  onOriginalPageChange: vi.fn(),
  onShowJsonChange: vi.fn(),
}

describe('OriginalTab page sync', () => {
  it('moves the parsed text with the preview for HWP documents aligned to preview pages', () => {
    render(
      <OriginalTab
        {...baseProps}
        isPdfDoc={false}
        originalPage={2}
        pagesTextResult={{ pages: [{ page_number: 1, text: '첫 쪽 글' }, { page_number: 2, text: '둘째 쪽 글' }], total_pages: 2, synced: true }}
      />,
    )

    expect(screen.getByText('둘째 쪽 글')).toBeInTheDocument()
    expect(screen.queryByText('문서 전체 본문')).not.toBeInTheDocument()
    expect(screen.getByText(/미리보기와 파싱 텍스트가 같은 쪽으로 함께 이동합니다/)).toBeInTheDocument()
  })

  it('shows the whole text when the preview could not be aligned', () => {
    render(
      <OriginalTab
        {...baseProps}
        isPdfDoc={false}
        originalPage={2}
        pagesTextResult={{ pages: [{ page_number: 1, text: '가' }, { page_number: 2, text: '나' }], total_pages: 2, synced: false }}
      />,
    )

    expect(screen.getByText('문서 전체 본문')).toBeInTheDocument()
    expect(screen.getByText(/원본 미리보기만 페이지 이동합니다/)).toBeInTheDocument()
  })

  it('lets a PDF reach trailing pages without text and says the page has no text', () => {
    render(
      <OriginalTab
        {...baseProps}
        isPdfDoc
        originalPage={8}
        pagesTextResult={{ pages: [{ page_number: 1, text: '본문' }, { page_number: 5, text: '끝' }], total_pages: 8, synced: true }}
      />,
    )

    expect(screen.getByText('8 / 8 쪽')).toBeInTheDocument()
    expect(screen.getByText(/이 쪽에서 추출된 글이 없습니다/)).toBeInTheDocument()
    // 원본 PDF 는 배율을 고를 수 있는 뷰어로 그 쪽을 그린다
    expect(screen.getByLabelText('원본 8쪽')).toBeInTheDocument()
    expect(screen.getByRole('toolbar', { name: '원본 배율' })).toBeInTheDocument()
  })

  it('starts the original and parsed text boxes on the same grid row, below one shared header row', () => {
    // 2026-11-27: 텍스트/JSON 선택이 파싱된 텍스트 칸 안에 있어 그 상자만 아래에서 시작했다
    render(
      <OriginalTab
        {...baseProps}
        isPdfDoc
        originalPage={1}
        pagesTextResult={{ pages: [{ page_number: 1, text: '본문' }], total_pages: 1, synced: true }}
      />,
    )

    const originalBody = screen.getByTestId('original-pane-body')
    const parsedBody = screen.getByTestId('parsed-pane-body')
    const grid = originalBody.parentElement as HTMLElement
    expect(parsedBody.parentElement).toBe(grid)
    expect(grid.style.gridTemplateRows).toBe('auto minmax(0, 1fr)')
    const cells = Array.from(grid.children)
    expect(cells.indexOf(originalBody)).toBe(2)
    expect(cells.indexOf(parsedBody)).toBe(3)
    const toggle = screen.getByRole('group', { name: '표시 모드 선택' })
    expect(cells[1].contains(toggle)).toBe(true)
    expect(parsedBody.contains(toggle)).toBe(false)
  })

  it('falls back to the browser PDF viewer when the PDF cannot be opened for drawing', async () => {
    pdfMocks.loadPdfDocument.mockRejectedValueOnce(new Error('broken'))

    render(
      <OriginalTab
        {...baseProps}
        isPdfDoc
        originalPage={3}
        pagesTextResult={{ pages: [{ page_number: 1, text: '본문' }], total_pages: 8, synced: true }}
      />,
    )

    expect(await screen.findByTitle('원본 문서')).toHaveAttribute('src', 'blob:pdf#page=3')
  })

  it('draws a stored table with its merged cells instead of the flat markdown', () => {
    const table = { page_number: 1, rows: [['구분', '소속', ''], ['작성', 'SOC', '']], spans: [{ row: 0, col: 1, row_span: 1, col_span: 2 }] }
    const markdown = ['| 구분 | 소속 |  |', '|---|---|---|', '| 작성 | SOC |  |'].join('\n')

    render(
      <OriginalTab
        {...baseProps}
        isPdfDoc={false}
        originalPage={1}
        content={{ full_text: `[표 1]\n${markdown}`, chunk_count: 1 }}
        pagesTextResult={undefined}
        tables={[table]}
      />,
    )

    expect(screen.getByText('소속').closest('td')).toHaveAttribute('colspan', '2')
    expect(screen.queryByText(/\|---\|/)).not.toBeInTheDocument()
  })
})
