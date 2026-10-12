import { describe, it, expect, beforeEach, vi } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'
import {
  useWorkflowRuns,
  useWorkflowRun,
  usePublishVersion,
  useSaveWorkflowGraph,
  useCreateDraftVersion,
  useDeleteVersion,
} from './useWorkflows'
import * as apiClientModule from '../lib/apiClient'

// Mock apiClient
vi.mock('../lib/apiClient', () => ({
  apiClient: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
    patch: vi.fn(),
  },
}))

type MockedApiClient = Record<'get' | 'post' | 'put' | 'delete' | 'patch', ReturnType<typeof vi.fn>>
const mockApiClient = apiClientModule.apiClient as unknown as MockedApiClient

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })
  return ({ children }: { children: React.ReactNode }) => React.createElement(
    QueryClientProvider,
    { client: queryClient },
    children,
  )
}

describe('useWorkflows polling and invalidation', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('useWorkflowRuns', () => {
    it('should fetch workflow runs for a specific workflow', async () => {
      const mockData = {
        data: {
          items: [
            {
              id: 'run1',
              version_id: 'v1',
              status: 'QUEUED' as const,
              started_at: null,
              completed_at: null,
              error_message: null,
              created_at: '2024-01-01T00:00:00Z',
            },
          ],
        },
      }

      mockApiClient.get.mockResolvedValue(mockData)

      const { result } = renderHook(() => useWorkflowRuns('w1'), {
        wrapper: createWrapper(),
      })

      await waitFor(() => {
        expect(result.current.data).toBeDefined()
        expect(result.current.data?.items).toHaveLength(1)
        expect(result.current.data?.items[0].status).toBe('QUEUED')
      })

      expect(mockApiClient.get).toHaveBeenCalledWith('/workflows/w1/runs')
    })

    it('should not fetch when workflowId is null', () => {
      renderHook(() => useWorkflowRuns(null), {
        wrapper: createWrapper(),
      })

      // Should not call API for null workflowId
      expect(mockApiClient.get).not.toHaveBeenCalledWith('/workflows/null/runs')
    })
  })

  describe('useWorkflowRun', () => {
    it('should fetch workflow run details', async () => {
      const mockData = {
        data: {
          run: {
            id: 'run1',
            version_id: 'v1',
            status: 'COMPLETED' as const,
            started_at: '2024-01-01T00:00:01Z',
            completed_at: '2024-01-01T00:00:10Z',
            error_message: null,
            created_at: '2024-01-01T00:00:00Z',
          },
          steps: [],
        },
      }

      mockApiClient.get.mockResolvedValue(mockData)

      const { result } = renderHook(() => useWorkflowRun('run1'), {
        wrapper: createWrapper(),
      })

      await waitFor(() => {
        expect(result.current.data).toBeDefined()
        expect(result.current.data?.run.status).toBe('COMPLETED')
      })

      expect(mockApiClient.get).toHaveBeenCalledWith('/workflows/runs/run1')
    })

    it('should not fetch when runId is null', () => {
      renderHook(() => useWorkflowRun(null), {
        wrapper: createWrapper(),
      })

      expect(mockApiClient.get).not.toHaveBeenCalledWith('/workflows/runs/null')
    })
  })

  describe('mutation invalidation', () => {
    it('useSaveWorkflowGraph should invalidate workflow-graph query', async () => {
      const queryClient = new QueryClient({
        defaultOptions: { mutations: { retry: false } },
      })

      const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')

      mockApiClient.put.mockResolvedValue({
        data: { saved: true, validation_errors: [] },
      })

      const wrapper = ({ children }: { children: React.ReactNode }) =>
        React.createElement(QueryClientProvider, { client: queryClient }, children)

      const { result } = renderHook(() => useSaveWorkflowGraph(), { wrapper })

      await act(async () => {
        await result.current.mutateAsync({
          workflowId: 'w1',
          versionId: 'v1',
          graph: { blocks: [], edges: [] },
        })
      })

      await waitFor(() => {
        expect(invalidateSpy).toHaveBeenCalledWith({
          queryKey: ['workflow-graph', 'w1', 'v1'],
        })
      })
    })

    it('usePublishVersion should invalidate workflow-versions and workflow queries', async () => {
      const queryClient = new QueryClient({
        defaultOptions: { mutations: { retry: false } },
      })

      const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')

      mockApiClient.post.mockResolvedValue({
        data: { message: 'Published', version_number: 1 },
      })

      const wrapper = ({ children }: { children: React.ReactNode }) =>
        React.createElement(QueryClientProvider, { client: queryClient }, children)

      const { result } = renderHook(() => usePublishVersion(), { wrapper })

      await act(async () => {
        await result.current.mutateAsync({
          workflowId: 'w1',
          versionId: 'v1',
        })
      })

      await waitFor(() => {
        expect(invalidateSpy).toHaveBeenCalledWith({
          queryKey: ['workflow-versions', 'w1'],
        })
        expect(invalidateSpy).toHaveBeenCalledWith({
          queryKey: ['workflow', 'w1'],
        })
      })
    })

    it('useCreateDraftVersion should invalidate workflow-versions query', async () => {
      const queryClient = new QueryClient({
        defaultOptions: { mutations: { retry: false } },
      })

      const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')

      mockApiClient.post.mockResolvedValue({
        data: {
          id: 'v2',
          workflow_id: 'w1',
          version_number: 2,
          published_at: null,
          created_at: '2024-01-02T00:00:00Z',
        },
      })

      const wrapper = ({ children }: { children: React.ReactNode }) =>
        React.createElement(QueryClientProvider, { client: queryClient }, children)

      const { result } = renderHook(() => useCreateDraftVersion(), { wrapper })

      await act(async () => {
        await result.current.mutateAsync('w1')
      })

      await waitFor(() => {
        expect(invalidateSpy).toHaveBeenCalledWith({
          queryKey: ['workflow-versions', 'w1'],
        })
      })
    })

    it('useDeleteVersion should invalidate workflow-versions query', async () => {
      const queryClient = new QueryClient({
        defaultOptions: { mutations: { retry: false } },
      })

      const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')

      mockApiClient.delete.mockResolvedValue({
        data: { deleted: true },
      })

      const wrapper = ({ children }: { children: React.ReactNode }) =>
        React.createElement(QueryClientProvider, { client: queryClient }, children)

      const { result } = renderHook(() => useDeleteVersion(), { wrapper })

      await act(async () => {
        await result.current.mutateAsync({
          workflowId: 'w1',
          versionId: 'v1',
        })
      })

      await waitFor(() => {
        expect(invalidateSpy).toHaveBeenCalledWith({
          queryKey: ['workflow-versions', 'w1'],
        })
      })
    })
  })
})
