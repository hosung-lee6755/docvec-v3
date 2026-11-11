import { describe, it, expect, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { DeepSearchProgress, DeepSearchSteps, DeepSearchToggle } from './DeepSearch'
import type { AgentSteps } from '../../hooks/useChat'

const steps: AgentSteps = {
  subquestions: [
    { question: '2027년 영업 목표는?', searches: 1, supplemented: false, hit_count: 3,
      documents: [{ document_id: 'd1', filename: 'sales.docx' }] },
    { question: '2026년 영업 실적은?', searches: 2, supplemented: true, hit_count: 2,
      documents: [{ document_id: null, filename: null, hidden: true }] },
  ],
  decomposed: true,
  fallback_to_original: false,
  evidence_count: 5,
  timings_ms: { plan: 21000, search: 3000, answer: 30000, verify: 12000 },
}

describe('DeepSearch', () => {
  it('toggles deep search', () => {
    const onChange = vi.fn()
    render(<DeepSearchToggle checked={false} onChange={onChange} />)
    fireEvent.click(screen.getByRole('switch', { name: /심층 검색/ }))
    expect(onChange).toHaveBeenCalledWith(true)
  })

  it('shows which sub-question is being searched', () => {
    render(<DeepSearchProgress progress={{ phase: 'searching', subquestions: ['목표?', '실적?'], current: 1 }} />)
    expect(screen.getByText(/하위 질문별로 문서를 찾는 중/)).toBeInTheDocument()
    expect(screen.getByText('목표? (완료)')).toBeInTheDocument()
    expect(screen.getByText('실적? (찾는 중)')).toBeInTheDocument()
  })

  it('starts with the planning phase before any progress arrives', () => {
    render(<DeepSearchProgress progress={null} />)
    expect(screen.getByText(/하위 질문으로 나누는 중/)).toBeInTheDocument()
  })

  it('lists each sub-question with its documents and hides documents the viewer cannot see', () => {
    render(<DeepSearchSteps steps={steps} />)
    const toggle = screen.getByRole('button', { name: /검색 과정 \(하위 질문 2개 · 근거 5건 · 66.0초\)/ })
    expect(screen.queryByText('2027년 영업 목표는?')).not.toBeInTheDocument()

    fireEvent.click(toggle)

    expect(screen.getByText('2027년 영업 목표는?')).toBeInTheDocument()
    expect(screen.getByText('sales.docx')).toBeInTheDocument()
    expect(screen.getByText('(볼 수 없는 문서)')).toBeInTheDocument()
    expect(screen.getByText(/근거가 약해 한 번 더 찾음/)).toBeInTheDocument()
  })
})
