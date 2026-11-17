import { describe, it, expect, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import ChunkEditPanel from './ChunkEditPanel'
import type { DocumentChunk2 } from '../../hooks/useDocuments'

const chunk = (id: string, index: number, text: string, embedded = false) =>
  ({ id, chunk_index: index, text, embedded, page_number: 1, disabled: false, edited: false } as DocumentChunk2)

function setup({ prev = chunk('p', 0, '앞 청크 본문'), next = chunk('n', 2, '뒤 청크 본문') as DocumentChunk2 | null } = {}) {
  const merge = { mutate: vi.fn(), isPending: false, isError: false, error: null }
  const update = { mutate: vi.fn(), isPending: false, isError: false, error: null }
  render(
    <ChunkEditPanel
      documentId="d1"
      chunk={chunk('c', 1, '짧음')}
      prevChunk={prev}
      nextChunk={next}
      text="짧음"
      updateChunk={update as never}
      mergeChunk={merge as never}
      onTextChange={vi.fn()}
      onClose={vi.fn()}
    />,
  )
  return { merge, update }
}

describe('ChunkEditPanel', () => {
  it('merges the chunk into the previous one and previews the result', () => {
    const { merge } = setup()

    fireEvent.click(screen.getByRole('radio', { name: '앞 청크에 합치기' }))

    expect(screen.getByLabelText('합친 결과 미리보기').textContent).toContain('앞 청크 본문\n짧음')
    fireEvent.click(screen.getByRole('button', { name: '합치기' }))
    expect(merge.mutate).toHaveBeenCalledWith({ docId: 'd1', chunkId: 'c', direction: 'prev' }, expect.anything())
  })

  it('disables merging forward when there is no next chunk', () => {
    setup({ next: null })

    expect(screen.getByRole('radio', { name: '뒤 청크에 합치기' })).toBeDisabled()
  })

  it('saves edited text of a chunk that is not embedded yet without promising re-embedding', () => {
    const { update } = setup()

    fireEvent.click(screen.getByRole('button', { name: '저장' }))

    expect(update.mutate).toHaveBeenCalledWith({ docId: 'd1', chunkId: 'c', text: '짧음' }, expect.anything())
  })
})
