import { describe, expect, it } from 'vitest'
import type { DocumentChunk2 } from '../../hooks/useDocuments'
import { toRagRecordsJson } from './documentDetailHelpers'

function chunk(overrides: Partial<DocumentChunk2>): DocumentChunk2 {
  return {
    id: 'c1', chunk_index: 0, text: '본문', page_number: 1, disabled: false, edited: false, hit_count: 0,
    embedded: true, token_count: 3, chunk_type: 'PARAGRAPH', keywords: ['예산'], embedding_model: 'bge-m3',
    element_id: 'el-1', prev_chunk_id: null, next_chunk_id: null, workflow_version: 1, dictionary_version: null,
    total_chunks: 2, char_count: 2, section_path: ['Ⅰ. 개요', '1. 목적'], heading_path: ['Ⅰ. 개요', '1. 목적'],
    language: 'ko', source_file: 'a.pdf', version: null, parent_chunk_text: '상위', ...overrides,
  } as DocumentChunk2
}

const DOC = { id: 'd1', original_filename: 'a.pdf', title: '제목', language: 'ko', security_level: 'internal' }

describe('toRagRecordsJson', () => {
  it('shows stored chunk records with structure metadata, not blank-line blocks', () => {
    const json = JSON.parse(toRagRecordsJson(DOC, [chunk({}), chunk({ id: 'c2', chunk_index: 1, disabled: true, parent_chunk_text: null })]))

    expect(json.document).toEqual({ id: 'd1', filename: 'a.pdf', title: '제목', language: 'ko', security_level: 'internal' })
    expect(json.chunk_count).toBe(2)
    expect(json.chunks[0]).toMatchObject({
      section_path: ['Ⅰ. 개요', '1. 목적'], chunk_type: 'PARAGRAPH', element_id: 'el-1', page: 1,
      search_excluded: false, has_parent_context: true, text: '본문',
    })
    expect(json.chunks[1]).toMatchObject({ search_excluded: true, has_parent_context: false })
    expect(json).not.toHaveProperty('blocks')
  })

  it('shows which table and parent cell a table chunk came from', () => {
    // 2026-11-20: 칸 안에서 떼어 낸 표 B 가 표 A 의 어느 칸에 있었는지 JSON 에서 바로 보이게 한다
    const table = {
      table_id: 'tB', table_number: 2, title: '[칸 안의 표 1] [표 1]의 칸에 든 표',
      parent_table_id: 'tA', parent_table_number: 1, parent_cell: { row: 3, col: 2 },
    }
    const json = JSON.parse(toRagRecordsJson(DOC, [chunk({ chunk_type: 'TABLE', table }), chunk({ id: 'c2' })]))

    expect(json.chunks[0].table).toEqual(table)
    expect(json.chunks[1]).not.toHaveProperty('table')
  })

  it('keeps only chunks that start on the given page', () => {
    const json = JSON.parse(toRagRecordsJson(DOC, [chunk({}), chunk({ id: 'c2', page_number: 2 })], 2))

    expect(json.chunks.map((c: { id: string }) => c.id)).toEqual(['c2'])
  })
})
