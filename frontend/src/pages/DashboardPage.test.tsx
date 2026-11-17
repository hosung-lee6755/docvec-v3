import { describe, it, expect, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import DashboardPage from './DashboardPage'

vi.mock('../lib/apiClient', () => ({
  apiClient: { get: vi.fn().mockResolvedValue({ data: { total_documents: 0, processing: 0, indexed: 0, collections: 0 } }) },
}))
vi.mock('../hooks/useDocuments', () => ({ useDocuments: () => ({ data: { items: [], total: 0 } }) }))
vi.mock('../hooks/useSearchHistory', () => ({ useSearchHistory: () => ({ data: { items: [] } }) }))
vi.mock('../hooks/useProjects', () => ({ useProjects: () => ({ data: { items: [] } }) }))
vi.mock('../store/authStore', () => ({
  useAuthStore: (select: (s: { user: { username: string; role: string } }) => unknown) =>
    select({ user: { username: '홍길동', role: 'viewer' } }),
}))

function Where() {
  const location = useLocation()
  return <div data-testid="where">{location.pathname}</div>
}

function renderDashboard() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="*" element={<Where />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('DashboardPage header actions', () => {
  it('offers new collection, new project and upload with the same button style', () => {
    renderDashboard()

    const labels = ['새 컬렉션', '새 프로젝트', '문서 업로드']
    const buttons = labels.map((name) => screen.getByRole('button', { name }))

    const styles = new Set(buttons.map((b) => b.className))
    expect(styles.size).toBe(1)
  })

  it('opens the new project form from the dashboard', () => {
    renderDashboard()

    fireEvent.click(screen.getByRole('button', { name: '새 프로젝트' }))

    expect(screen.getByTestId('where').textContent).toBe('/projects')
  })
})
