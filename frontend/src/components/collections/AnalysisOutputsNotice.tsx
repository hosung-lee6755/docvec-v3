import { useWorkflowGraph, useWorkflowVersions } from '../../hooks/useWorkflows'
import { missingAnalysisOutputs, missingAnalysisOutputsMessage } from '../../lib/analysisOutputs'
import { Alert } from '../ui'

type Props = {
  workflowId: string
  // null 이면 항상 최신 게시 버전을 쓰는 지정이다
  pinnedVersion: number | null
}

/**
 * 컬렉션에 분석 워크플로우를 지정할 때, 그 워크플로우가 만들지 않는 항목(요약, 추천 태그, 분류)을 알린다(2026-11-20).
 * 분석은 사용자 워크플로우를 그대로 따르고, 만들지 않는 항목은 문서에서 비운다(backend/app/pipeline/analysis_outputs.py).
 */
export function AnalysisOutputsNotice({ workflowId, pinnedVersion }: Props) {
  const { data: versions } = useWorkflowVersions(workflowId)
  const published = (versions?.items ?? [])
    .filter((v) => v.published_at)
    .sort((a, b) => b.version_number - a.version_number)
  const target = pinnedVersion != null
    ? published.find((v) => v.version_number === pinnedVersion)
    : published[0]
  const { data: graph } = useWorkflowGraph(target ? workflowId : null, target?.id ?? null)
  if (!graph) return null
  const message = missingAnalysisOutputsMessage(missingAnalysisOutputs(graph.blocks))
  if (!message) return null
  return <Alert tone="warning">{message}</Alert>
}
