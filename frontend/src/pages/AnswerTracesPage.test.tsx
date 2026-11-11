import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import AnswerTracesPage from './AnswerTracesPage'

let role = 'admin'
const listArgs: unknown[] = []

vi.mock('../store/authStore', () => ({
  useAuthStore: (select: (s: { user: { role: string } }) => unknown) => select({ user: { role } }),
}))

vi.mock('../hooks/useAnswerTraces', () => ({
  useAnswerTraces: (filters: unknown) => {
    listArgs.push(filters)
    return {
      isLoading: false,
      isError: false,
      data: {
        total: 1,
        items: [{
          id: 't-1', created_at: '2026-11-11T01:00:00Z', user_id: 'u-1', username: 'asker',
          query: '휴가 규정 알려줘', status: 'DONE', grounding: 'failed', broadened: true,
          cache_hit: false, model_key: 'qwen2.5-3b', source_count: 2, cited_count: 1,
        }],
      },
    }
  },
  useAnswerTrace: (id: string | null) => ({
    isLoading: false,
    isError: false,
    data: id && {
      id, created_at: '2026-11-11T01:00:00Z', username: 'asker', user_role: 'viewer',
      clearance_level: 'Internal', group_ids: ['g-1'], accessible_collection_count: 3,
      access_fingerprint: 'fp', scope_collection_id: null, scope_project_id: null, intent: 'chunk_search',
      broadened: true, grounding: 'failed', cache_hit: false, model_key: 'qwen2.5-3b', provider: 'local',
      verifier_model: 'qwen2.5-3b', system_prompt_source: 'default', input_tokens: null, output_tokens: null,
      latency_ms: 1200, query: '휴가 규정 알려줘', answer: '연차는 15일입니다[1]', status: 'DONE', error_message: null,
      sources: [
        { rank: 1, document_id: 'd-1', collection_id: 'c-1', filename: '취업규칙.pdf', security_level: 'Internal',
          page_number: 3, source_kind: 'chunk', chunk_ref: 'p-1', score: 0.8, cited: true, access: 'visible',
          text: '연차휴가는 15일로 한다', text_changed: true },
        { rank: 2, document_id: null, collection_id: null, filename: null, security_level: null,
          page_number: null, source_kind: 'chunk', chunk_ref: null, score: null, cited: false, access: 'hidden',
          text: null, text_changed: null },
      ],
    },
  }),
}))

const renderPage = (path = '/answer-traces') =>
  render(<MemoryRouter initialEntries={[path]}><AnswerTracesPage /></MemoryRouter>)

describe('AnswerTracesPage', () => {
  beforeEach(() => {
    role = 'admin'
    listArgs.length = 0
  })

  it('is admin only', () => {
    role = 'viewer'
    renderPage()
    expect(screen.getByText('관리자만 접근할 수 있습니다.')).toBeInTheDocument()
  })

  it('lists traces with grounding and citation counts', () => {
    renderPage()
    const table = within(screen.getByRole('table'))
    expect(table.getByText('asker')).toBeInTheDocument()
    expect(table.getByText('근거 부족')).toBeInTheDocument()
    expect(table.getByText('2건 중 1건 인용')).toBeInTheDocument()
  })

  it('opens the detail with visible text and a hidden source without text', () => {
    renderPage()
    fireEvent.click(screen.getByRole('button', { name: '휴가 규정 알려줘' }))

    const detail = screen.getByRole('region', { name: '답변 추적 상세' })
    expect(detail).toHaveTextContent('연차휴가는 15일로 한다')
    expect(detail).toHaveTextContent('답변 이후 문서가 바뀜')
    expect(detail).toHaveTextContent('문서 정보 비공개')
    expect(detail).toHaveTextContent('열람 권한 없음')
    expect(detail).toHaveTextContent('AI가 생성한 답변')
  })

  it('prefills the document filter from the URL for reverse lookup', () => {
    renderPage('/answer-traces?document_id=d-9')
    expect(screen.getByLabelText('근거 문서 ID로 찾기')).toHaveValue('d-9')
    expect(listArgs[0]).toMatchObject({ document_id: 'd-9' })
  })
})
