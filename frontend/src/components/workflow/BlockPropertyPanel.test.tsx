import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import BlockPropertyPanel from './BlockPropertyPanel'
import type { WorkflowBlock } from '../../hooks/useWorkflows'

vi.mock('../../hooks/useWorkflows', () => ({
  useBlockTypes: () => ({
    data: { items: [{
      block_type: 'pii_detect',
      config_schema: { properties: {
        entity_types: { anyOf: [{ type: 'array', items: { type: 'string' } }, { type: 'null' }] },
        mask_char: { type: 'string', default: '*' },
      } },
    }] },
  }),
}))
vi.mock('../../hooks/useCollections', () => ({ useEmbeddingModels: () => ({ data: undefined }) }))
vi.mock('../../hooks/useDictionary', () => ({ useDictionaryEntries: () => ({ data: undefined }) }))

function block(config: Record<string, unknown>): WorkflowBlock {
  return { id: 'b1', block_type: 'pii_detect', label: null, config, position: { x: 0, y: 0 } } as unknown as WorkflowBlock
}

function renderPanel(config: Record<string, unknown>, onChange = vi.fn()) {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <BlockPropertyPanel block={block(config)} onChange={onChange} />
    </QueryClientProvider>,
  )
  return onChange
}

describe('BlockPropertyPanel 선택형 입력', () => {
  it('고정 선택지 배열 필드는 체크박스이고 선택지 순서대로 저장한다', () => {
    const onChange = renderPanel({ entity_types: ['PHONE'] })

    fireEvent.click(screen.getByLabelText('주민등록번호'))

    expect(onChange).toHaveBeenCalledWith('b1', { config: { entity_types: ['RRN', 'PHONE'] } })
  })

  it('모두 해제하면 키를 지워 전체 적용으로 돌아간다', () => {
    const onChange = renderPanel({ entity_types: ['PHONE'] })

    fireEvent.click(screen.getByLabelText('전화번호'))

    expect(onChange).toHaveBeenCalledWith('b1', { config: {} })
  })

  it('마스킹 문자는 자유 입력이 아니라 select 이다', () => {
    renderPanel({})

    expect(screen.getByRole('combobox')).toBeTruthy()
  })
})
