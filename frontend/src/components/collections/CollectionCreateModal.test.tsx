import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { CollectionCreateModal } from './CollectionCreateModal'

const mutateAsync = vi.fn()

vi.mock('../../hooks/useCollections', () => ({
  useCreateCollection: () => ({ mutateAsync, isPending: false, isError: false }),
}))

vi.mock('../../hooks/useWorkflows', () => ({
  useWorkflows: (_projectId: string | null, kind: string) => ({
    data: kind === 'ANALYSIS'
      ? { items: [
        { id: 'std', name: '표준 분석 워크플로우', is_system_default: true, project_id: null },
        { id: 'kw', name: '키워드만', is_system_default: false, project_id: 'p-1' },
      ] }
      : { items: [] },
  }),
  useWorkflowVersions: () => ({
    data: { items: [{ id: 'kw-v1', workflow_id: 'kw', version_number: 1, published_at: '2026-11-20', created_at: '' }] },
  }),
  useWorkflowGraph: (_workflowId: string | null, versionId: string | null) => ({
    data: versionId === 'kw-v1'
      ? { blocks: ['input', 'extract_keywords', 'output'].map((block_type, i) => ({ id: `b${i}`, block_type, label: null, position: {}, config: {} })), edges: [] }
      : undefined,
  }),
}))

describe('CollectionCreateModal', () => {
  beforeEach(() => {
    mutateAsync.mockReset()
    mutateAsync.mockResolvedValue({ id: 'col-1' })
  })

  it('sends the chosen default security level', async () => {
    render(<CollectionCreateModal projects={[]} routeProjectId="p-1" initialProjectId="p-1" onClose={vi.fn()} />)

    fireEvent.change(screen.getByLabelText('이름 *'), { target: { value: '인사 문서' } })
    fireEvent.change(screen.getByLabelText('기본 보안등급'), { target: { value: 'Confidential' } })
    fireEvent.click(screen.getByRole('button', { name: '만들기' }))

    await waitFor(() => expect(mutateAsync).toHaveBeenCalled())
    expect(mutateAsync.mock.calls[0][0]).toMatchObject({ name: '인사 문서', default_security_level: 'Confidential' })
  })

  it('leaves the level unset when none is chosen', async () => {
    render(<CollectionCreateModal projects={[]} routeProjectId="p-1" initialProjectId="p-1" onClose={vi.fn()} />)

    fireEvent.change(screen.getByLabelText('이름 *'), { target: { value: '공지' } })
    fireEvent.click(screen.getByRole('button', { name: '만들기' }))

    await waitFor(() => expect(mutateAsync).toHaveBeenCalled())
    expect(mutateAsync.mock.calls[0][0].default_security_level).toBeUndefined()
  })

  it('분석 워크플로우를 고르면 그 워크플로우가 만들지 않는 항목을 알린다', () => {
    render(<CollectionCreateModal projects={[]} routeProjectId="p-1" initialProjectId="p-1" onClose={vi.fn()} />)
    const select = screen.getByLabelText('기본 분석 워크플로우')
    expect(screen.queryByRole('option', { name: '표준 분석 워크플로우' })).toBeNull()
    expect(screen.queryByRole('alert')).toBeNull()

    fireEvent.change(select, { target: { value: 'kw' } })

    expect(screen.getByRole('alert')).toHaveTextContent('이 워크플로우에는 요약, 분류 단계가 없습니다.')
  })

  it('프로젝트를 바꾸면 고른 워크플로우를 표준으로 되돌리고 알린다', () => {
    const projects = [{ id: 'p-1', name: '첫 프로젝트' }, { id: 'p-2', name: '둘째 프로젝트' }]
    render(<CollectionCreateModal projects={projects} routeProjectId={undefined} initialProjectId="p-1" onClose={vi.fn()} />)
    fireEvent.change(screen.getByLabelText('기본 분석 워크플로우'), { target: { value: 'kw' } })

    fireEvent.change(screen.getByLabelText('프로젝트'), { target: { value: 'p-2' } })

    expect(screen.getByLabelText('기본 분석 워크플로우')).toHaveValue('')
    expect(screen.getByText(/'키워드만' 분석 워크플로우는 새 프로젝트에서 쓸 수 없어 표준으로 바뀝니다/)).toBeInTheDocument()
  })

  it('개인 컬렉션에는 프로젝트 워크플로우가 보이지 않는다', () => {
    render(<CollectionCreateModal projects={[{ id: 'p-1', name: '첫 프로젝트' }]} routeProjectId={undefined} initialProjectId="" onClose={vi.fn()} />)
    expect(screen.queryByRole('option', { name: '키워드만' })).toBeNull()
  })
})
