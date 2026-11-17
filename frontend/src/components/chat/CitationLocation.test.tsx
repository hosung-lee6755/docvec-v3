import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { CitationLocation } from './CitationLocation'

const mocks = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('../../lib/apiClient', () => ({ apiClient: { get: mocks.get } }))

const wrap = (ui: React.ReactElement) => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

// jsdom의 Blob에는 text()가 없어 브라우저처럼 읽히게 붙인다
const errorBlob = (status: number, detail: string) => {
  const body = JSON.stringify({ detail })
  return { response: { status, data: Object.assign(new Blob([body]), { text: () => Promise.resolve(body) }) } }
}

const context = {
  chunk_id: 'c1',
  located: true,
  before: '앞 문맥 ',
  text: '인용된 <b>문장</b>',
  after: ' 뒤 문맥',
  has_more_before: true,
  has_more_after: false,
  section_path: ['2장 운영', '2.1 백업'],
  page_start: null,
  page_end: null,
}

describe('CitationLocation', () => {
  beforeEach(() => mocks.get.mockReset())

  it('is disabled with the reason for answers made before locations were stored', () => {
    wrap(<CitationLocation documentId="d1" chunkId={null} filename="a.txt" index={1} />)

    const button = screen.getByRole('button', { name: /위치 보기/ })
    expect(button).toBeDisabled()
    // 막힌 버튼은 마우스 이벤트를 받지 못해 설명은 감싼 요소에 둔다
    expect(button.parentElement).toHaveAttribute('title', expect.stringContaining('예전 답변'))
    fireEvent.click(button)
    expect(mocks.get).not.toHaveBeenCalled()
  })

  it('does not request anything until the button is pressed', () => {
    wrap(<CitationLocation documentId="d1" chunkId="c1" filename="a.pdf" index={1} />)

    expect(mocks.get).not.toHaveBeenCalled()
  })

  it('shows the highlighted page image when the document has a page rendering', async () => {
    mocks.get.mockResolvedValueOnce({
      data: new Blob(['png']), headers: { 'x-highlight-page': '3', 'x-highlight-count': '2' },
    })
    URL.createObjectURL = vi.fn(() => 'blob:page')
    URL.revokeObjectURL = vi.fn()
    wrap(<CitationLocation documentId="d1" chunkId="c1" filename="a.pdf" index={1} />)

    fireEvent.click(screen.getByRole('button', { name: /위치 보기/ }))

    expect(await screen.findByRole('img')).toBeInTheDocument()
    expect(mocks.get).toHaveBeenCalledTimes(1)
    expect(mocks.get.mock.calls[0][0]).toBe('/documents/d1/chunks/c1/highlight')
  })

  it('falls back to the text context when the format has no page rendering', async () => {
    mocks.get
      .mockRejectedValueOnce(errorBlob(422, '이 형식은 쪽 단위 위치 표시를 지원하지 않습니다'))
      .mockResolvedValueOnce({ data: context })
    wrap(<CitationLocation documentId="d1" chunkId="c1" filename="a.html" index={2} />)

    fireEvent.click(screen.getByRole('button', { name: /위치 보기/ }))

    const marked = await screen.findByText('인용된 <b>문장</b>')
    // 글은 마크업이 아니라 글자로 그려진다(HTML이 해석되지 않는다)
    expect(marked.tagName).toBe('MARK')
    expect(marked.querySelector('b')).toBeNull()
    expect(screen.getByText(/앞 문맥/)).toBeInTheDocument()
    expect(screen.getByText(/뒤 문맥/)).toBeInTheDocument()
    expect(screen.getByText('2장 운영 > 2.1 백업')).toBeInTheDocument()
    expect(mocks.get.mock.calls[1][0]).toBe('/documents/d1/chunks/c1/context')
  })

  it('says so when the cited part could not be placed in the text', async () => {
    mocks.get
      .mockRejectedValueOnce(errorBlob(422, '이 형식은 쪽 단위 위치 표시를 지원하지 않습니다'))
      .mockResolvedValueOnce({ data: { ...context, located: false, before: '', after: '', has_more_before: false } })
    wrap(<CitationLocation documentId="d1" chunkId="c1" filename="a.txt" index={1} />)

    fireEvent.click(screen.getByRole('button', { name: /위치 보기/ }))

    expect(await screen.findByText(/문서 안의 정확한 자리를 찾지 못/)).toBeInTheDocument()
    expect(screen.getByText('인용된 <b>문장</b>')).toBeInTheDocument()
  })

  it('shows the server reason when the chunk is gone and does not try the text view', async () => {
    mocks.get.mockRejectedValueOnce(errorBlob(404, '문서를 다시 처리해 이 인용의 위치 정보가 없습니다'))
    wrap(<CitationLocation documentId="d1" chunkId="c1" filename="a.pdf" index={1} />)

    fireEvent.click(screen.getByRole('button', { name: /위치 보기/ }))

    expect(await screen.findByText(/다시 처리해 이 인용의 위치 정보가 없습니다/)).toBeInTheDocument()
    await waitFor(() => expect(mocks.get).toHaveBeenCalledTimes(1))
  })
})
