import { describe, it, expect, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import MoveCollectionControl from './MoveCollectionControl'
import { summarizeMoveResults } from '../../hooks/useDocuments'

const COLLECTIONS = [{ id: 'a', name: '기존' }, { id: 'b', name: '대상' }]

describe('MoveCollectionControl', () => {
  it('moves to the chosen collection and hides the current one from the choices', () => {
    const onMove = vi.fn()
    render(<MoveCollectionControl collections={COLLECTIONS} currentCollectionId="a" isPending={false} onMove={onMove} />)

    fireEvent.click(screen.getByRole('button', { name: /컬렉션 이동/ }))
    const select = screen.getByLabelText('옮길 컬렉션')
    expect(screen.queryByRole('option', { name: '기존' })).toBeNull()
    expect(screen.getByRole('button', { name: '이동' })).toBeDisabled()
    fireEvent.change(select, { target: { value: 'b' } })
    fireEvent.click(screen.getByRole('button', { name: '이동' }))

    expect(onMove).toHaveBeenCalledWith('b')
  })
})

describe('summarizeMoveResults', () => {
  it('reports moved documents and the first reason a document stayed', () => {
    const summary = summarizeMoveResults([
      { id: '1', status: 'moved', detail: null },
      { id: '2', status: 'skipped', detail: '처리 중인 문서는 옮길 수 없습니다.' },
    ])

    expect(summary).toEqual({ text: '옮김 1건, 옮기지 못함 1건(처리 중인 문서는 옮길 수 없습니다.)', isError: false })
  })
})
