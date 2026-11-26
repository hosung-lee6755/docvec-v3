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

  it('keeps chunks whose page range covers the given page', () => {
    // 2026-11-26: 시작 쪽만 보아 1~2쪽에 걸친 청크가 2쪽 JSON 에서 빠졌다
    const chunks = [chunk({}), chunk({ id: 'c2', page_number: 1, page_end: 2 }), chunk({ id: 'c3', page_number: 2 })]
    const json = JSON.parse(toRagRecordsJson(DOC, chunks, { page_number: 2 }))

    expect(json.chunks.map((c: { id: string }) => c.id)).toEqual(['c2', 'c3'])
    expect(json.chunks[0]).toMatchObject({ page: 1, page_end: 2 })
  })

  it('picks chunks by the page text span when the page carries its position in the body', () => {
    // HWP·DOCX 는 쪽을 미리보기 PDF 에 맞춰 나눠, 청크의 쪽 번호보다 본문 위치가 쪽 글과 정확히 맞는다
    const chunks = [
      chunk({ id: 'c1', page_number: 1, span_start: 0, span_end: 10 }),
      chunk({ id: 'c2', page_number: 1, span_start: 10, span_end: 25 }),
      chunk({ id: 'c3', page_number: 3, span_start: 25, span_end: 40 }),
    ]
    const json = JSON.parse(toRagRecordsJson(DOC, chunks, { page_number: 2, start: 12, end: 30 }))

    expect(json.chunks.map((c: { id: string }) => c.id)).toEqual(['c2', 'c3'])
  })
})

describe('legacyTablesToMarkdown', () => {
  it('turns an older HWP table written as "a | b" rows into a markdown table', async () => {
    const { legacyTablesToMarkdown } = await import('./documentDetailHelpers')
    const text = '앞 문단\n\n[표 3]\n구분 | 품목 | \n개발 / 대상 | 컨테이너(환적) | 철광석\n\n뒤 문단'

    expect(legacyTablesToMarkdown(text)).toBe(
      '앞 문단\n\n[표 3]\n| 구분 | 품목 |  |\n|---|---|---|\n| 개발 / 대상 | 컨테이너(환적) | 철광석 |\n\n뒤 문단',
    )
  })

  it('keeps the inner table title line and leaves markdown tables and plain text alone', async () => {
    const { legacyTablesToMarkdown } = await import('./documentDetailHelpers')
    const markdown = '[표 1]\n| a | b |\n|---|---|\n| c | d |'
    const titled = '[표 2]\n[칸 안의 표 1] 제목\na | b'
    const prose = '본문에 | 기호가 들어간 줄'

    expect(legacyTablesToMarkdown(markdown)).toBe(markdown)
    expect(legacyTablesToMarkdown(titled)).toBe('[표 2]\n[칸 안의 표 1] 제목\n| a | b |\n|---|---|')
    expect(legacyTablesToMarkdown(prose)).toBe(prose)
  })
})
