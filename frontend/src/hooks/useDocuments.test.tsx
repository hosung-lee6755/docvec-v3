import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { useDocuments } from './useDocuments'

const get = vi.fn()
vi.mock('../lib/apiClient', () => ({ apiClient: { get: (...args: unknown[]) => get(...args) } }))

const wrapperFor = () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
}

describe('useDocuments lifecycle filter', () => {
  beforeEach(() => {
    get.mockReset()
    get.mockResolvedValue({ data: { items: [], total: 0, page: 1, limit: 20 } })
  })

  it('sends the lifecycle filter as a query parameter', async () => {
    renderHook(() => useDocuments({ lifecycle: 'archived' }), { wrapper: wrapperFor() })
    await waitFor(() => expect(get).toHaveBeenCalled())
    expect(get.mock.calls[0][1].params.lifecycle).toBe('archived')
  })

  it('omits the lifecycle parameter by default so superseded versions stay hidden', async () => {
    renderHook(() => useDocuments({}), { wrapper: wrapperFor() })
    await waitFor(() => expect(get).toHaveBeenCalled())
    expect(get.mock.calls[0][1].params.lifecycle).toBeUndefined()
  })
})
