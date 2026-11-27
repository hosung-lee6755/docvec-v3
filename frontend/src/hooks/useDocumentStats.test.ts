import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fetchDocumentStats } from './useDocumentStats'
import { apiClient } from '../lib/apiClient'

vi.mock('../lib/apiClient', () => ({ apiClient: { get: vi.fn() } }))

describe('fetchDocumentStats', () => {
  beforeEach(() => {
    vi.mocked(apiClient.get).mockResolvedValue({ data: { total_documents: 26 } })
  })

  it('asks for one project when the documents screen is inside a project', async () => {
    // 프로젝트 문서 화면 요약 띠가 모든 프로젝트를 세어 "전체 70" 옆 목록이 26건이었다(2026-11-26)
    await fetchDocumentStats('p1')

    expect(apiClient.get).toHaveBeenLastCalledWith('/stats', { params: { project_id: 'p1' } })
  })

  it('asks for every visible document on the dashboard', async () => {
    await fetchDocumentStats()

    expect(apiClient.get).toHaveBeenLastCalledWith('/stats', { params: undefined })
  })
})
