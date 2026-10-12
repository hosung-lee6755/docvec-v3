import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import ReprocessModal from './ReprocessModal'

const mutateAsync = vi.fn()

vi.mock('../hooks/useDocumentRuns', () => ({
  useDocumentRuns: () => ({ data: { runs: [] } }),
  useReprocessImpact: () => ({
    data: { affectedBlocks: [], affectedNodeCount: 0, affectedChunkCount: 0, fullReprocessingRequired: false },
    isLoading: false, isError: false,
  }),
  useStartPartialReprocess: () => ({ mutateAsync, isPending: false, isError: false }),
}))
vi.mock('../hooks/useWorkflows', () => ({ useWorkflowRun: () => ({ data: undefined }) }))

describe('ReprocessModal 최신 게시 버전 옵션', () => {
  beforeEach(() => mutateAsync.mockReset().mockResolvedValue({ run_id: 'r1' }))

  it('기본값은 끄기 — 이전 실행의 버전 그대로 재처리한다', async () => {
    render(<ReprocessModal documentId="d1" onClose={() => {}} />)

    fireEvent.click(screen.getByText('재처리 시작'))

    await waitFor(() => expect(mutateAsync).toHaveBeenCalled())
    expect(mutateAsync.mock.calls[0][0].useLatestVersion).toBe(false)
  })

  it('체크하면 useLatestVersion=true 로 요청한다', async () => {
    render(<ReprocessModal documentId="d1" onClose={() => {}} />)

    fireEvent.click(screen.getByLabelText('최신 게시 버전으로 처리'))
    fireEvent.click(screen.getByText('재처리 시작'))

    await waitFor(() => expect(mutateAsync).toHaveBeenCalled())
    expect(mutateAsync.mock.calls[0][0].useLatestVersion).toBe(true)
  })
})
