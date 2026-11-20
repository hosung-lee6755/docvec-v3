import { describe, expect, it } from 'vitest'
import { projectChangeNotice, workflowsForProject } from './workflowScope'

const wf = (id: string, project_id: string | null) => ({ id, project_id })

describe('workflowsForProject', () => {
  const items = [wf('sys', null), wf('a1', 'A'), wf('b1', 'B')]

  it('같은 프로젝트의 워크플로우만 고를 수 있다', () => {
    expect(workflowsForProject(items, 'A').map((w) => w.id)).toEqual(['a1'])
  })

  it('개인 컬렉션은 프로젝트 워크플로우를 고를 수 없다(표준만 쓴다)', () => {
    expect(workflowsForProject(items, '')).toEqual([])
    expect(workflowsForProject(items, null)).toEqual([])
  })

  it('목록이 아직 없으면 빈 목록이다', () => {
    expect(workflowsForProject(undefined, 'A')).toEqual([])
  })
})

describe('projectChangeNotice', () => {
  it('되돌아가는 지정을 이름으로 알린다', () => {
    expect(projectChangeNotice({ preprocess: '작은 청크', analysis: '요약만' })).toBe(
      "프로젝트를 바꾸면 '작은 청크' 전처리 워크플로우, '요약만' 분석 워크플로우는 새 프로젝트에서 쓸 수 없어 표준으로 바뀝니다. 저장해야 적용됩니다.",
    )
    expect(projectChangeNotice({ analysis: '요약만' })).toBe(
      "프로젝트를 바꾸면 '요약만' 분석 워크플로우는 새 프로젝트에서 쓸 수 없어 표준으로 바뀝니다. 저장해야 적용됩니다.",
    )
  })

  it('되돌아가는 지정이 없으면 알리지 않는다', () => {
    expect(projectChangeNotice({})).toBeNull()
  })
})
