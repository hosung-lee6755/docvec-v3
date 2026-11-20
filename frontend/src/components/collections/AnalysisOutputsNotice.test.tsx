import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { AnalysisOutputsNotice } from './AnalysisOutputsNotice'

const graphFor = vi.fn()

vi.mock('../../hooks/useWorkflows', () => ({
  useWorkflowVersions: () => ({
    data: {
      items: [
        { id: 'v1', workflow_id: 'wf', version_number: 1, published_at: '2026-11-01', created_at: '' },
        { id: 'v2', workflow_id: 'wf', version_number: 2, published_at: '2026-11-10', created_at: '' },
        { id: 'v3', workflow_id: 'wf', version_number: 3, published_at: null, created_at: '' },
      ],
    },
  }),
  useWorkflowGraph: (_workflowId: string | null, versionId: string | null) => ({ data: graphFor(versionId) }),
}))

const graph = (...types: string[]) => ({
  blocks: types.map((block_type, i) => ({ id: `b${i}`, block_type, label: null, position: {}, config: {} })),
  edges: [],
})

describe('AnalysisOutputsNotice', () => {
  it('최신 게시 버전에 없는 항목을 알린다', () => {
    graphFor.mockImplementation((versionId: string | null) =>
      versionId === 'v2' ? graph('input', 'extract_keywords', 'output') : graph('input', 'summarize', 'classify', 'output'))
    render(<AnalysisOutputsNotice workflowId="wf" pinnedVersion={null} />)
    expect(screen.getByRole('alert')).toHaveTextContent('이 워크플로우에는 요약, 분류 단계가 없습니다.')
  })

  it('고정한 버전의 구성을 본다', () => {
    graphFor.mockImplementation((versionId: string | null) =>
      versionId === 'v1' ? graph('input', 'summarize', 'output') : graph('input', 'summarize', 'extract_keywords', 'classify', 'output'))
    render(<AnalysisOutputsNotice workflowId="wf" pinnedVersion={1} />)
    expect(screen.getByRole('alert')).toHaveTextContent('추천 태그, 분류 단계가 없습니다.')
  })

  it('요약, 태그, 분류를 모두 만들면 아무것도 보이지 않는다', () => {
    graphFor.mockReturnValue(graph('input', 'summarize', 'extract_keywords', 'classify', 'output'))
    const { container } = render(<AnalysisOutputsNotice workflowId="wf" pinnedVersion={null} />)
    expect(container).toBeEmptyDOMElement()
  })
})
