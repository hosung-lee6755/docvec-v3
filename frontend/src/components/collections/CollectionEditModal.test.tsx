import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { CollectionEditModal } from './CollectionEditModal'
import type { Collection } from '../../hooks/useCollections'

const reprocessChunks = vi.fn()
const reprocessFromStart = vi.fn()

vi.mock('../../hooks/useCollections', () => ({
  useUpdateCollection: () => ({ mutateAsync: vi.fn(), isPending: false, isError: false }),
  useReprocessCollection: () => ({ mutateAsync: reprocessChunks, isPending: false, isError: false }),
  useReprocessCollectionFromStart: () => ({ mutateAsync: reprocessFromStart, isPending: false, isError: false }),
}))

vi.mock('../../hooks/useWorkflows', () => ({
  useWorkflows: () => ({ data: { items: [] } }),
  useWorkflowVersions: () => ({ data: { items: [] } }),
  useWorkflowGraph: () => ({ data: undefined }),
}))

vi.mock('./SearchSettingsSection', () => ({ SearchSettingsSection: () => null }))

const collection = {
  id: 'col-1',
  name: '로컬 폴더 점검',
  description: null,
  project_id: 'p-1',
  default_security_level: null,
  default_workflow_id: null,
  default_workflow_version: null,
  default_analysis_workflow_id: null,
  default_analysis_workflow_version: null,
  document_count: 15,
} as unknown as Collection

function renderModal() {
  render(<CollectionEditModal collection={collection} projects={[]} routeProjectId="p-1" onClose={vi.fn()} />)
}

describe('CollectionEditModal 재처리 버튼', () => {
  beforeEach(() => {
    reprocessChunks.mockReset()
    reprocessFromStart.mockReset()
  })

  it('처음부터 다시 처리는 확인을 거쳐 추출부터 다시 돌리고 건너뛴 이유를 보여 준다', async () => {
    reprocessFromStart.mockResolvedValue({
      queued: 14,
      skipped: 1,
      skipped_reasons: { '원본 실행이 아직 완료되지 않았습니다.': 1 },
    })
    renderModal()

    fireEvent.click(screen.getByRole('button', { name: '처음부터 다시 처리 (추출부터)' }))
    fireEvent.click(screen.getByRole('button', { name: '확인' }))

    await waitFor(() => expect(reprocessFromStart).toHaveBeenCalledWith('col-1'))
    expect(reprocessChunks).not.toHaveBeenCalled()
    expect(await screen.findByText(/14건 처음부터 재처리 시작됨/)).toBeTruthy()
    expect(screen.getByText(/원본 실행이 아직 완료되지 않았습니다\. 1건/)).toBeTruthy()
  })

  it('청크와 임베딩만 다시 만드는 버튼은 예전 일괄 재처리를 부른다', async () => {
    reprocessChunks.mockResolvedValue({ queued: 15, skipped: 0 })
    renderModal()

    fireEvent.click(screen.getByRole('button', { name: '청크·임베딩만 다시 만들기' }))
    fireEvent.click(screen.getByRole('button', { name: '확인' }))

    await waitFor(() => expect(reprocessChunks).toHaveBeenCalledWith('col-1'))
    expect(reprocessFromStart).not.toHaveBeenCalled()
  })
})
