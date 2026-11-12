import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, within } from '@testing-library/react'
import GoldenEvalModal from './GoldenEvalModal'
import type { GoldenEvalRun } from '../hooks/useGoldenQueries'

const mocks = vi.hoisted(() => ({
  goldenQueries: vi.fn(),
  runs: vi.fn(),
  runEval: vi.fn(),
  setBaseline: vi.fn(),
  updateQuery: vi.fn(),
}))

vi.mock('../hooks/useGoldenQueries', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../hooks/useGoldenQueries')>()
  return {
    ...actual,
    useGoldenQueries: () => mocks.goldenQueries(),
    useCreateGoldenQuery: () => ({ mutateAsync: vi.fn(), isPending: false, isError: false }),
    useDeleteGoldenQuery: () => ({ mutate: vi.fn() }),
    useUpdateGoldenQuery: () => mocks.updateQuery(),
    useGoldenEvalRuns: () => mocks.runs(),
    useRunGoldenEval: () => mocks.runEval(),
    useSetGoldenBaseline: () => mocks.setBaseline(),
  }
})

vi.mock('../hooks/useDocuments', () => ({
  useDocuments: () => ({ data: { items: [{ id: 'doc-1', original_filename: 'energy.pdf' }] } }),
}))

const mutation = (mutate = vi.fn()) => ({ mutate, mutateAsync: vi.fn(), isPending: false, isError: false, error: null })

const run = (overrides: Partial<GoldenEvalRun>): GoldenEvalRun => ({
  id: 'run-1',
  collection_id: 'col-1',
  top_k: 5,
  status: 'DONE',
  trigger: 'manual',
  mean_precision: 0.5,
  mean_recall: 0.6,
  mean_hit_rate: 0.7,
  mean_mrr: 0.4,
  is_baseline: false,
  is_regression: false,
  regression: null,
  search_settings: null,
  error_message: null,
  results: [],
  created_at: '2026-11-01T00:00:00Z',
  completed_at: '2026-11-01T00:01:00Z',
  ...overrides,
})

const renderModal = () =>
  render(<GoldenEvalModal collectionId="col-1" collectionName="검증 컬렉션" onClose={vi.fn()} />)

describe('GoldenEvalModal', () => {
  beforeEach(() => {
    mocks.goldenQueries.mockReturnValue({
      data: { items: [{ id: 'gq-1', collection_id: 'col-1', query: '에너지 절감?', expected_document_ids: ['doc-1'], created_at: '' }] },
    })
    mocks.runs.mockReturnValue({ data: { items: [] } })
    mocks.runEval.mockReturnValue(mutation())
    mocks.setBaseline.mockReturnValue(mutation())
    mocks.updateQuery.mockReturnValue(mutation())
  })

  it('shows a regression banner with the metric drop and the lost queries', () => {
    mocks.runs.mockReturnValue({
      data: {
        items: [run({
          is_regression: true,
          regression: {
            baseline_run_id: 'run-0',
            tolerance: 0.05,
            metrics: { mean_hit_rate: { baseline: 0.8, current: 0.5, delta: -0.3 } },
            regressed_metrics: ['mean_hit_rate'],
            lost_queries: [{ golden_query_id: 'gq-1', query: '에너지 절감?' }],
          },
        })],
      },
    })
    renderModal()
    const banner = screen.getByRole('alert')
    expect(within(banner).getByText(/기준 실행보다 검색 품질이 떨어졌습니다/)).toBeInTheDocument()
    expect(within(banner).getByText('적중률: 80.0% → 50.0%')).toBeInTheDocument()
    expect(within(banner).getByText('에너지 절감?')).toBeInTheDocument()
  })

  it('offers to make a finished run the baseline, but not the current baseline itself', () => {
    const setBaseline = vi.fn()
    mocks.setBaseline.mockReturnValue(mutation(setBaseline))
    mocks.runs.mockReturnValue({
      data: {
        items: [
          run({ id: 'run-2', created_at: '2026-11-02T00:00:00Z' }),
          run({ id: 'run-1', is_baseline: true }),
        ],
      },
    })
    renderModal()
    const buttons = screen.getAllByRole('button', { name: '기준으로 삼기' })
    expect(buttons).toHaveLength(1)
    fireEvent.click(buttons[0])
    expect(setBaseline).toHaveBeenCalledWith('run-2')
    expect(screen.getByText('기준')).toBeInTheDocument()
  })

  it('sends no top_k when the field is blank so the collection setting applies', () => {
    const runEval = vi.fn()
    mocks.runEval.mockReturnValue(mutation(runEval))
    renderModal()
    fireEvent.click(screen.getByRole('button', { name: '평가 실행' }))
    expect(runEval).toHaveBeenCalledWith(null)
  })

  it('disables running when top_k is outside 1 to 20', () => {
    renderModal()
    fireEvent.change(screen.getByLabelText(/top-K/), { target: { value: '25' } })
    expect(screen.getByRole('button', { name: '평가 실행' })).toBeDisabled()
    expect(screen.getByRole('alert')).toHaveTextContent('1에서 20 사이')
  })

  it('shows the run status and its trigger label while a run is still queued', () => {
    mocks.runs.mockReturnValue({
      data: { items: [run({ status: 'QUEUED', trigger: 'new_version', results: null })] },
    })
    renderModal()
    expect(screen.getAllByText('대기 중').length).toBeGreaterThan(0)
    expect(screen.getAllByText('새 버전 반영').length).toBeGreaterThan(0)
  })
})
