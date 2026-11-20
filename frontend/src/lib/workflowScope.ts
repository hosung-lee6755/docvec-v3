/**
 * 워크플로우를 쓸 수 있는 곳(2026-11-20). 백엔드 backend/app/services/workflow_scope.py 와 같은 규칙이다.
 * 시스템 워크플로우는 어디서나 쓰고(화면에서는 "표준 (시스템 기본값)" 선택지), 프로젝트 워크플로우는
 * 같은 프로젝트의 컬렉션에만 쓴다. 개인 컬렉션은 표준만 쓴다.
 */

interface ScopedWorkflow {
  project_id: string | null
}

/** 컬렉션 화면의 선택지에 넣을 프로젝트 워크플로우. 개인 컬렉션이면 없다. */
export function workflowsForProject<T extends ScopedWorkflow>(
  items: readonly T[] | undefined,
  projectId: string | null | undefined,
): T[] {
  if (!projectId) return []
  return (items ?? []).filter((w) => w.project_id === projectId)
}

/** 컬렉션의 프로젝트를 바꿀 때 표준으로 되돌아가는 지정을 알리는 문구. */
export function projectChangeNotice(names: { preprocess?: string | null; analysis?: string | null }): string | null {
  const parts = [
    names.preprocess ? `'${names.preprocess}' 전처리 워크플로우` : null,
    names.analysis ? `'${names.analysis}' 분석 워크플로우` : null,
  ].filter((part): part is string => part !== null)
  if (parts.length === 0) return null
  return `프로젝트를 바꾸면 ${parts.join(', ')}는 새 프로젝트에서 쓸 수 없어 표준으로 바뀝니다. 저장해야 적용됩니다.`
}
