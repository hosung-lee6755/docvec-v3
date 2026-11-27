import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import SearchPage from './SearchPage'

const post = vi.fn()
vi.mock('../lib/apiClient', () => ({ apiClient: { post: (...args: unknown[]) => post(...args), get: vi.fn() } }))
vi.mock('../hooks/useCollections', () => ({ useCollections: () => ({ data: { items: [] }, isLoading: false }) }))
vi.mock('../hooks/useDocuments', () => ({ useAllTags: () => ({ data: { tags: [] } }) }))
vi.mock('../hooks/useSearchHistory', () => ({ useSearchHistory: () => ({ data: { items: [] } }) }))

const RESULT = {
  chunk_id: 'c1',
  score: 0.82,
  document_id: 'd1',
  content: '제11조(요양보상) ① 임직원이 업무상 입은 부상 또는 질병으로 …',
  metadata: { filename: 'old-name.hwp' },
  bm25_score: null,
  final_score: null,
  evidence: null,
  filename: '복리후생규정.hwp',
  collection_name: '규정집',
  project_id: 'p1',
  project_name: '인사 운영',
  page_number: 2,
  page_end: 3,
  section_path: ['제4장 재해보상', '제11조(요양보상)'],
}

function renderSearch(path = '/search') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/search" element={<SearchPage />} />
          <Route path="/projects/:projectId/search" element={<SearchPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

async function searchFor(text: string) {
  fireEvent.change(screen.getByPlaceholderText('문서 내용 검색...'), { target: { value: text } })
  fireEvent.click(screen.getByRole('button', { name: '검색' }))
  return screen.findByText(RESULT.content)
}

describe('SearchPage results', () => {
  beforeEach(() => {
    post.mockReset()
    post.mockResolvedValue({ data: { items: [RESULT], expanded_query: '요양보상', added_terms: [] } })
  })

  it('shows the same source place as a chat citation: project, collection, document, pages and section', async () => {
    // 2026-11-27: 검색 결과는 문서 이름과 점수만 보여, 채팅 인용처럼 어느 프로젝트·컬렉션의 어느 자리인지 알 수 없었다
    renderSearch()

    await searchFor('요양보상')

    expect(screen.getByText('인사 운영')).toBeInTheDocument()
    expect(screen.getByText('규정집')).toBeInTheDocument()
    expect(screen.getByText('복리후생규정.hwp')).toBeInTheDocument()
    expect(screen.getByText('2–3쪽 · 제4장 재해보상 > 제11조(요양보상)')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '위치 보기' })).toBeEnabled()
  })

  it('opens the document in a new tab so the results stay, inside the project when searched there', async () => {
    const open = vi.spyOn(window, 'open').mockReturnValue(null)
    renderSearch('/projects/p9/search')

    await searchFor('요양보상')
    fireEvent.click(screen.getByRole('button', { name: '문서 열기' }))

    expect(open).toHaveBeenCalledWith('/projects/p9/documents/d1', '_blank', 'noopener')
    open.mockRestore()
  })

  it('searches like chat by default and says whether the results were reranked', async () => {
    // 2026-11-27: 화면 기본값이 의미 검색이라 채팅보다 결과가 나빴고, 재순위는 채팅에서만 한다고 안내했다
    post.mockResolvedValue({ data: {
      items: [{ ...RESULT, final_score: 0.4, bm25_score: 0.3, rerank_score: 0.91 }],
      expanded_query: '요양보상', added_terms: [],
      applied: { mode: 'hybrid', diversify: false, vector_weight: 0.6, rerank_in_chat: true, from_collection: false, reranked: true },
    } })
    renderSearch()

    await searchFor('요양보상')

    expect(post.mock.calls[0][1]).toMatchObject({ mode: 'hybrid' })
    expect(screen.getByText(/재순위 적용/)).toBeInTheDocument()
    expect(screen.getByText(/91.0%/)).toBeInTheDocument()
  })
})
