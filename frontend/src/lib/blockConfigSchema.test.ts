import { describe, expect, it } from 'vitest'
import { jsonSchemaToConfigFields, type JsonSchema } from './blockConfigSchema'

const field = (schema: JsonSchema, blockType: string, key: string) =>
  jsonSchemaToConfigFields(schema, blockType).find((f) => f.key === key)

describe('jsonSchemaToConfigFields — 자유 입력을 선택으로', () => {
  it('text_extract.engine 은 legacy/docling 선택이다', () => {
    const f = field({ properties: { engine: { type: 'string', default: 'legacy' } } }, 'text_extract', 'engine')
    expect(f?.type).toBe('select')
    expect(f?.options?.map((o) => o.value)).toEqual(['legacy', 'docling'])
  })

  it('ocr.engine / ocr.language 는 선택이다', () => {
    const schema: JsonSchema = { properties: { engine: { type: 'string' }, language: { type: 'string' } } }
    expect(field(schema, 'ocr', 'engine')?.type).toBe('select')
    expect(field(schema, 'ocr', 'language')?.options?.map((o) => o.value)).toContain('ko+en')
  })

  it('pii_detect.mask_char 는 선택이다', () => {
    const f = field({ properties: { mask_char: { type: 'string' } } }, 'pii_detect', 'mask_char')
    expect(f?.type).toBe('select')
    expect(f?.options?.map((o) => o.value)).toContain('*')
  })

  it('고정 선택지가 있는 배열 필드는 다중 선택(list + options)이다', () => {
    const arr: JsonSchema = { properties: {
      entity_types: { anyOf: [{ type: 'array', items: { type: 'string' } }, { type: 'null' }] },
      term_types: { anyOf: [{ type: 'array', items: { type: 'string' } }, { type: 'null' }] },
      allowed_extensions: { type: 'array', items: { type: 'string' } },
    } }
    expect(field(arr, 'pii_detect', 'entity_types')?.options?.map((o) => o.value))
      .toEqual(['RRN', 'PHONE', 'EMAIL', 'ACCOUNT', 'CARD', 'NAME'])
    expect(field(arr, 'user_dict', 'term_types')?.options?.length).toBe(8)
    expect(field(arr, 'file_validate', 'allowed_extensions')?.options?.map((o) => o.value))
      .toEqual(['.pdf', '.docx', '.hwp', '.hwpx'])
    for (const [bt, k] of [['pii_detect', 'entity_types'], ['user_dict', 'term_types'], ['file_validate', 'allowed_extensions']]) {
      expect(field(arr, bt, k)?.type).toBe('list')
    }
  })

  it('선택지가 없는 문자열 필드는 그대로 text 이다', () => {
    expect(field({ properties: { foo: { type: 'string' } } }, 'ocr', 'foo')?.type).toBe('text')
  })
})
