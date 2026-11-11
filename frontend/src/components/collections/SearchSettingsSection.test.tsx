import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { SearchSettingsSection } from './SearchSettingsSection'
import type { Collection } from '../../hooks/useCollections'

const mutate = vi.fn()

vi.mock('../../hooks/useCollections', async () => {
  const actual = await vi.importActual<typeof import('../../hooks/useCollections')>('../../hooks/useCollections')
  return { ...actual, useUpdateCollection: () => ({ mutate, isPending: false, isError: false, isSuccess: false }) }
})

const collection = (overrides: Partial<Collection> = {}): Collection =>
  ({ id: 'col-1', name: '테스트', ...overrides }) as Collection

describe('SearchSettingsSection', () => {
  beforeEach(() => mutate.mockReset())

  it('starts from the defaults and keeps save disabled until something changes', () => {
    render(<SearchSettingsSection collection={collection()} />)
    expect(screen.getByLabelText('검색 방식')).toHaveValue('hybrid')
    expect(screen.getByRole('button', { name: '검색 설정 저장' })).toBeDisabled()
  })

  it('saves only the search settings of this collection', () => {
    render(<SearchSettingsSection collection={collection()} />)
    fireEvent.change(screen.getByLabelText('검색 방식'), { target: { value: 'vector' } })
    // 의미 검색이면 비중 슬라이더는 의미가 없으므로 숨긴다
    expect(screen.queryByLabelText('의미 비중')).not.toBeInTheDocument()
    fireEvent.click(screen.getByLabelText('재순위'))
    fireEvent.click(screen.getByRole('button', { name: '검색 설정 저장' }))

    expect(mutate).toHaveBeenCalledWith({
      id: 'col-1',
      search_settings: { mode: 'vector', top_k: 5, rerank: false, diversify: false, vector_weight: 0.6 },
    })
  })

  it('resets the draft to the defaults without saving', () => {
    render(<SearchSettingsSection collection={collection({
      search_settings: { mode: 'vector', top_k: 8, rerank: false, diversify: true, vector_weight: 0.3 },
    })} />)
    fireEvent.click(screen.getByRole('button', { name: '기본값으로' }))
    expect(screen.getByLabelText('검색 방식')).toHaveValue('hybrid')
    expect(mutate).not.toHaveBeenCalled()
  })

  it('never submits the surrounding collection form', () => {
    render(<SearchSettingsSection collection={collection()} />)
    for (const button of screen.getAllByRole('button')) expect(button).toHaveAttribute('type', 'button')
  })
})
