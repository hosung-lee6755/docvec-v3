import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import OriginalTab from './OriginalTab'

vi.mock('../../hooks/usePdfBlobUrl', () => ({
  usePdfBlobUrl: () => ({ blobUrl: 'blob:pdf', isLoading: false, isError: false }),
}))
vi.mock('./pdfjsLoader', () => ({
  loadPdfDocument: vi.fn(async () => ({
    numPages: 2,
    getPage: async () => ({
      getViewport: ({ scale }: { scale: number }) => ({ width: 600 * scale, height: 800 * scale }),
      render: () => ({ promise: Promise.resolve(), cancel: () => {} }),
    }),
    destroy: async () => {},
  })),
}))
HTMLCanvasElement.prototype.getContext = vi.fn(() => null) as unknown as HTMLCanvasElement['getContext']

const props = {
  isContentLoading: false,
  isPreviewError: false,
  content: { full_text: '', chunk_count: 1 },
  ragSource: {} as never,
  chunksResult: undefined,
  previewResult: { kind: 'pdf' as const, url: 'https://minio/preview.pdf' },
  showJson: false,
  onOriginalPageChange: vi.fn(),
  onShowJsonChange: vi.fn(),
  isPdfDoc: false,
}

describe('OriginalTab table continued across pages', () => {
  it('draws the rows continued on the next page as a table without an empty head', () => {
    const pages = [
      { page_number: 1, text: '[표 1]\n| 항구 | 물동량 |\n| --- | --- |\n| 부산 | 120 |\n' },
      { page_number: 2, text: '| 인천 | 80 |\n| 광양 | 60 |\n\n다음 문단' },
    ]

    const { container } = render(
      <OriginalTab {...props} originalPage={2} pagesTextResult={{ pages, total_pages: 2, synced: true }} />,
    )

    expect(screen.getByRole('table')).toBeInTheDocument()
    expect(screen.getByRole('cell', { name: '인천' })).toBeInTheDocument()
    expect(container.querySelector('thead')).toBeNull()
    expect(container.textContent).not.toContain('| 인천')
  })
})
