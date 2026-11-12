import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, within } from '@testing-library/react'
import VersionHistoryPanel from './VersionHistoryPanel'
import type { DocumentVersion } from '../../hooks/useDocumentLifecycle'

const mocks = vi.hoisted(() => ({
  versions: vi.fn(),
  compare: vi.fn(),
  archive: vi.fn(),
  restore: vi.fn(),
  setExpiry: vi.fn(),
}))

vi.mock('../../hooks/useDocumentLifecycle', () => ({
  useDocumentVersions: () => mocks.versions(),
  useCompareVersions: () => mocks.compare(),
  useArchiveDocument: () => mocks.archive(),
  useRestoreVersion: () => mocks.restore(),
  useSetDocumentExpiry: () => mocks.setExpiry(),
}))

const mutation = (mutate = vi.fn()) => ({ mutate, isPending: false, isError: false, error: null })

const version = (overrides: Partial<DocumentVersion>): DocumentVersion => ({
  id: 'v-1',
  version_number: 1,
  lifecycle_state: 'superseded',
  status: 'INDEXED',
  filename: 'report.pdf',
  file_size: 1024,
  created_at: '2026-01-01T00:00:00Z',
  created_by: null,
  expires_at: null,
  archived_at: null,
  is_retrievable: false,
  ...overrides,
})

const current = version({ id: 'v-2', version_number: 2, lifecycle_state: 'current', is_retrievable: true })
const previous = version({ id: 'v-1', version_number: 1, lifecycle_state: 'superseded' })

describe('VersionHistoryPanel', () => {
  beforeEach(() => {
    mocks.versions.mockReturnValue({
      isLoading: false, isError: false, data: { lineage_id: 'v-2', items: [current, previous] },
    })
    mocks.compare.mockReturnValue({ isLoading: false, isError: false, data: undefined })
    mocks.archive.mockReturnValue(mutation())
    mocks.restore.mockReturnValue(mutation())
    mocks.setExpiry.mockReturnValue(mutation())
  })

  it('lists every version with its lifecycle state and search indicator', () => {
    render(<VersionHistoryPanel documentId="v-2" />)
    const items = screen.getAllByRole('listitem')
    expect(items).toHaveLength(2)
    expect(within(items[0]).getByText('2번 버전')).toBeInTheDocument()
    expect(within(items[0]).getByText('현재 버전')).toBeInTheDocument()
    expect(within(items[0]).getByText('검색에 쓰임')).toBeInTheDocument()
    expect(within(items[1]).getByText('이전 버전')).toBeInTheDocument()
    expect(within(items[1]).queryByText('검색에 쓰임')).not.toBeInTheDocument()
  })

  it('offers restore only for indexed previous versions and archive only for the current one', () => {
    render(<VersionHistoryPanel documentId="v-2" />)
    const items = screen.getAllByRole('listitem')
    expect(within(items[1]).getByRole('button', { name: '이 버전을 현재 버전으로' })).toBeInTheDocument()
    expect(within(items[0]).queryByRole('button', { name: '이 버전을 현재 버전으로' })).not.toBeInTheDocument()
    expect(within(items[0]).getByRole('button', { name: '보관' })).toBeInTheDocument()
    expect(within(items[1]).queryByRole('button', { name: '보관' })).not.toBeInTheDocument()
  })

  it('restores a previous version only after the user confirms', () => {
    const restore = vi.fn()
    mocks.restore.mockReturnValue(mutation(restore))
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    render(<VersionHistoryPanel documentId="v-2" />)
    fireEvent.click(screen.getByRole('button', { name: '이 버전을 현재 버전으로' }))
    expect(restore).not.toHaveBeenCalled()
    confirm.mockReturnValue(true)
    fireEvent.click(screen.getByRole('button', { name: '이 버전을 현재 버전으로' }))
    expect(restore).toHaveBeenCalledWith('v-1')
    confirm.mockRestore()
  })

  it('renders the diff lines with added and removed counts', () => {
    mocks.compare.mockReturnValue({
      isLoading: false,
      isError: false,
      data: {
        base_id: 'v-1', base_version: 1, target_id: 'v-2', target_version: 2,
        added_lines: 1, removed_lines: 1, truncated: true,
        diff: ['@@ -1 +1 @@', '-예전 문장', '+새 문장'],
      },
    })
    render(<VersionHistoryPanel documentId="v-2" />)
    fireEvent.click(screen.getByRole('button', { name: '현재 버전과 비교' }))
    expect(screen.getByText(/1번 버전 → 2번 버전 · 추가 1줄 · 삭제 1줄/)).toBeInTheDocument()
    expect(screen.getByText(/앞부분만 보여줍니다/)).toBeInTheDocument()
    expect(screen.getByText('+새 문장')).toHaveStyle({ color: '#15803d' })
    expect(screen.getByText('-예전 문장')).toHaveStyle({ color: '#b91c1c' })
  })

  it('shows the server detail when a restore is refused', () => {
    mocks.restore.mockReturnValue({
      ...mutation(),
      isError: true,
      error: { response: { data: { detail: '인덱싱이 끝난 버전만 되돌릴 수 있습니다.' } } },
    })
    render(<VersionHistoryPanel documentId="v-2" />)
    expect(screen.getByRole('alert')).toHaveTextContent('인덱싱이 끝난 버전만 되돌릴 수 있습니다.')
  })
})
