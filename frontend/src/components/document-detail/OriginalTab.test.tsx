import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import OriginalTab from './OriginalTab'

vi.mock('../../hooks/usePdfBlobUrl', () => ({
  usePdfBlobUrl: () => ({ blobUrl: 'blob:pdf', isLoading: false, isError: false }),
}))
vi.mock('react-markdown', () => ({ default: ({ children }: { children: string }) => <div>{children}</div> }))

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
    expect(screen.getByTitle('원본 문서')).toHaveAttribute('src', 'blob:pdf#page=8')
  })
})
