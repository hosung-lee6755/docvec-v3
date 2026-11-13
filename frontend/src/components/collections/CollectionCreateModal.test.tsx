import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { CollectionCreateModal } from './CollectionCreateModal'

const mutateAsync = vi.fn()

vi.mock('../../hooks/useCollections', () => ({
  useCreateCollection: () => ({ mutateAsync, isPending: false, isError: false }),
}))

vi.mock('../../hooks/useWorkflows', () => ({
  useWorkflows: () => ({ data: [] }),
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
})
