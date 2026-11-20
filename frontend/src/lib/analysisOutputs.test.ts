import { describe, expect, it } from 'vitest'
import { analysisOutputs, missingAnalysisOutputs, missingAnalysisOutputsMessage } from './analysisOutputs'

const block = (block_type: string, config: Record<string, unknown> = {}) => ({ block_type, config })

describe('analysisOutputs', () => {
  it('표준 분석 사슬은 요약, 태그, 분류를 모두 남긴다', () => {
    const blocks = [block('input'), block('summarize'), block('extract_keywords'), block('classify'), block('output')]
    expect(analysisOutputs(blocks)).toEqual(new Set(['summary', 'tags', 'category']))
  })

  it('출력 블록이 없거나 문서에 저장하지 않으면 아무것도 남기지 않는다', () => {
    expect(analysisOutputs([block('summarize'), block('classify')]).size).toBe(0)
    expect(analysisOutputs([block('summarize'), block('output', { save_to_document: false })]).size).toBe(0)
  })

  it('분류를 태그로 쓰지 않으면 분류만 남긴다', () => {
    expect(analysisOutputs([block('classify'), block('output')])).toEqual(new Set(['category', 'tags']))
    expect(analysisOutputs([block('classify'), block('output', { category_as_tag: false })])).toEqual(new Set(['category']))
  })

  it('키워드나 개체 블록은 태그를 남긴다', () => {
    expect(analysisOutputs([block('extract_keywords'), block('output')])).toEqual(new Set(['tags']))
    expect(analysisOutputs([block('extract_entities'), block('output')])).toEqual(new Set(['tags']))
  })
})

describe('missingAnalysisOutputsMessage', () => {
  it('빠지는 항목을 이름으로 알린다', () => {
    const missing = missingAnalysisOutputs([block('input'), block('extract_keywords'), block('output')])
    expect(missing).toEqual(['요약', '분류'])
    expect(missingAnalysisOutputsMessage(missing)).toBe(
      '이 워크플로우에는 요약, 분류 단계가 없습니다. 이 컬렉션 문서의 요약, 분류는 비워 두고 채우지 않습니다.',
    )
  })

  it('빠지는 항목이 없으면 알리지 않는다', () => {
    const missing = missingAnalysisOutputs([block('summarize'), block('extract_keywords'), block('classify'), block('output')])
    expect(missing).toEqual([])
    expect(missingAnalysisOutputsMessage(missing)).toBeNull()
  })
})
