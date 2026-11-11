import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import OcrConfidencePanel from './OcrConfidencePanel'

const get = vi.fn()
vi.mock('../../lib/apiClient', () => ({ apiClient: { get: (url: string) => get(url) } }))

const renderPanel = () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <OcrConfidencePanel documentId="doc-1" />
    </QueryClientProvider>,
  )
}

describe('OcrConfidencePanel', () => {
  beforeEach(() => get.mockReset())

  it('lists the pages that fall below the threshold', async () => {
    get.mockResolvedValue({ data: {
      ocr_used: true, threshold: 0.5, page_count: 2, mean_confidence: 0.6, low_pages: [2],
      pages: [
        { page_number: 1, confidence: 0.9, word_count: 120, low: false },
        { page_number: 2, confidence: 0.3, word_count: 40, low: true },
      ],
    } })
    renderPanel()
    expect(await screen.findByText(/기준 미달 1쪽\(2쪽\)/)).toBeInTheDocument()
    expect(get).toHaveBeenCalledWith('/documents/doc-1/ocr-confidence')
    expect(screen.getAllByRole('listitem')).toHaveLength(2)
  })

  it('explains when the document needed no OCR', async () => {
    get.mockResolvedValue({ data: { ocr_used: false, threshold: 0.5, page_count: 3, mean_confidence: null, low_pages: [], pages: [] } })
    renderPanel()
    expect(await screen.findByText(/OCR을 하지 않았습니다/)).toBeInTheDocument()
  })
})
