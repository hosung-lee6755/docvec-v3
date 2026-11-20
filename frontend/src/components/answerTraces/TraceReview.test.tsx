import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import type { AnswerTraceDetail } from '../../hooks/useAnswerTraces'
import { TraceReview } from './TraceReview'

const setReview = vi.fn()
const register = vi.fn()

vi.mock('../../hooks/useAnswerTraces', () => ({
  useSetTraceReview: () => ({ mutate: setReview, isPending: false, isError: false, error: null }),
  useRegisterTraceGoldenQuery: () => ({ mutate: register, isPending: false, isError: false, error: null }),
}))
vi.mock('../../hooks/useCollections', () => ({
  useCollections: () => ({
    data: { items: [{ id: 'col-a', name: '운영 문서' }, { id: 'col-b', name: '규정집' }] },
  }),
}))
vi.mock('../../hooks/useDocuments', () => ({
  useDocuments: ({ collectionId }: { collectionId?: string }) => ({
    data: {
      items: collectionId === 'col-a'
        ? [{ id: 'doc-1', original_filename: '운영메모.md' }, { id: 'doc-2', original_filename: '점검표.hwp' }]
        : [],
    },
  }),
}))

const trace = (overrides: Partial<AnswerTraceDetail> = {}) =>
  ({
    id: 't1',
    query: '선로전환기 점검 주기는?',
    scope_collection_id: 'col-a',
    review_cause: null,
    reviewed_by_name: null,
    reviewed_at: null,
    golden_query_id: null,
    golden_query_collection_id: null,
    sources: [{ rank: 1, document_id: 'doc-1', collection_id: 'col-a', access: 'visible', cited: true }],
    ...overrides,
  }) as AnswerTraceDetail

describe('TraceReview', () => {
  beforeEach(() => {
    setReview.mockReset()
    register.mockReset()
  })

  it('원인을 고르면 바로 저장한다', () => {
    render(<TraceReview trace={trace()} />)
    fireEvent.change(screen.getByRole('combobox', { name: '답변 문제의 원인' }), { target: { value: 'retrieval' } })
    expect(setReview).toHaveBeenCalledWith('retrieval')
  })

  it('표시를 지우면 null 을 보낸다', () => {
    render(<TraceReview trace={trace({ review_cause: 'answer', reviewed_by_name: 'admin', reviewed_at: '2026-11-20T01:00:00Z' })} />)
    expect(screen.getByText(/admin님이 표시했습니다/)).toBeInTheDocument()
    fireEvent.change(screen.getByRole('combobox', { name: '답변 문제의 원인' }), { target: { value: '' } })
    expect(setReview).toHaveBeenCalledWith(null)
  })

  it('이미 등록한 질문은 등록 버튼 대신 등록했다고 알린다', () => {
    render(<TraceReview trace={trace({ golden_query_id: 'gq1', golden_query_collection_id: 'col-a' })} />)
    expect(screen.getByText(/'운영 문서' 컬렉션의 골든 쿼리로 등록했습니다/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '골든 쿼리로 등록' })).not.toBeInTheDocument()
  })

  it('질문과 컬렉션을 채운 등록 양식을 열고 고른 기대 문서로 등록한다', () => {
    render(<TraceReview trace={trace()} />)
    fireEvent.click(screen.getByRole('button', { name: '골든 쿼리로 등록' }))

    expect(screen.getByRole('combobox', { name: '골든 쿼리를 넣을 컬렉션' })).toHaveValue('col-a')
    expect(screen.getByRole('textbox', { name: '골든 쿼리 질문' })).toHaveValue('선로전환기 점검 주기는?')
    expect(screen.getByText('이번 답변의 근거')).toBeInTheDocument()
    const submit = screen.getByRole('button', { name: '등록' })
    expect(submit).toBeDisabled()

    fireEvent.click(screen.getByRole('checkbox', { name: /점검표\.hwp/ }))
    fireEvent.change(screen.getByRole('textbox', { name: /기대 사실/ }), { target: { value: '6개월\n6개월\n' } })
    fireEvent.click(submit)
    expect(register).toHaveBeenCalledWith(
      { collection_id: 'col-a', query: '선로전환기 점검 주기는?', expected_document_ids: ['doc-2'], expected_facts: ['6개월'] },
      expect.anything(),
    )
  })

  it('컬렉션을 바꾸면 고른 기대 문서를 비운다', () => {
    render(<TraceReview trace={trace()} />)
    fireEvent.click(screen.getByRole('button', { name: '골든 쿼리로 등록' }))
    fireEvent.click(screen.getByRole('checkbox', { name: /운영메모\.md/ }))
    fireEvent.change(screen.getByRole('combobox', { name: '골든 쿼리를 넣을 컬렉션' }), { target: { value: 'col-b' } })
    expect(screen.getByText('이 컬렉션에 문서가 없습니다.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '등록' })).toBeDisabled()
  })
})
