/**
 * 분석 워크플로우가 문서에 남기는 항목(요약, 태그, 분류)을 블록 구성으로 판정한다(2026-11-20).
 *
 * 백엔드 backend/app/pipeline/analysis_outputs.py 와 같은 규칙이다. 문서에는 출력 블록(문서에 저장)이 쓰고,
 * 요약은 요약 블록, 태그는 키워드나 개체 블록(또는 분류를 태그로도 쓰는 분류 블록), 분류는 분류 블록이 있을 때 남는다.
 * 워크플로우에 없는 항목은 분석할 때 비워지므로, 컬렉션에 지정하는 화면에서 미리 알린다.
 */

export type AnalysisOutput = 'summary' | 'tags' | 'category'

interface BlockLike {
  block_type: string
  config?: Record<string, unknown> | null
}

const TAG_BLOCKS = new Set(['extract_keywords', 'extract_entities'])

const OUTPUT_LABELS: ReadonlyArray<[AnalysisOutput, string]> = [
  ['summary', '요약'],
  ['tags', '추천 태그'],
  ['category', '분류'],
]

export function analysisOutputs(blocks: readonly BlockLike[]): Set<AnalysisOutput> {
  const savers = blocks
    .filter((b) => b.block_type === 'output' && (b.config ?? {}).save_to_document !== false)
    .map((b) => b.config ?? {})
  if (savers.length === 0) return new Set()
  const types = new Set(blocks.map((b) => b.block_type))
  const produced = new Set<AnalysisOutput>()
  if (types.has('summarize')) produced.add('summary')
  if (types.has('classify')) produced.add('category')
  const categoryAsTag = types.has('classify') && savers.some((c) => c.category_as_tag !== false)
  if ([...types].some((t) => TAG_BLOCKS.has(t)) || categoryAsTag) produced.add('tags')
  return produced
}

/** 이 워크플로우가 만들지 않는 항목의 화면 이름(요약, 추천 태그, 분류 순서). */
export function missingAnalysisOutputs(blocks: readonly BlockLike[]): string[] {
  const produced = analysisOutputs(blocks)
  return OUTPUT_LABELS.filter(([key]) => !produced.has(key)).map(([, label]) => label)
}

export function missingAnalysisOutputsMessage(missing: readonly string[]): string | null {
  if (missing.length === 0) return null
  const names = missing.join(', ')
  return `이 워크플로우에는 ${names} 단계가 없습니다. 이 컬렉션 문서의 ${names}는 비워 두고 채우지 않습니다.`
}

/** 컬렉션의 "기본 분석 워크플로우" 칸 안내. 생성, 수정 화면이 함께 쓴다 */
export const ANALYSIS_WORKFLOW_HINT =
  '전처리가 끝나면 이 워크플로우가 문서마다 자동으로 실행됩니다. 워크플로우에 없는 단계의 결과(요약, 추천 태그, 분류)는 비워 둡니다. '
  + '지정하지 않으면 표준 분석 워크플로우가 요약, 키워드, 분류를 만듭니다.'
