import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { GitBranch, Loader2, MoreVertical, Plus, Trash2 } from 'lucide-react'
import {
  useCreateWorkflow, useDeleteWorkflow, useDuplicateWorkflow, useRenameWorkflow, useUpdateWorkflowStatus, useWorkflows,
  type WorkflowListItem,
} from '../hooks/useWorkflows'
import { useProjects } from '../hooks/useProjects'
import VersionCompareModal from '../components/workflow/VersionCompareModal'
import SetCollectionDefaultModal from '../components/workflow/SetCollectionDefaultModal'
import {
  Alert, Badge, Button, Field, IconButton, Input, Page, PageHeader, Select, StatStrip, Stat, Textarea,
  Toolbar, EmptyState, Modal,
} from '../components/ui'
import '../styles/screens/pipeline.css'

const KIND_LABELS: Record<string, string> = { PREPROCESS: '전처리', ANALYSIS: '분석' }

const STATUS_BADGE: Record<string, { label: string; tone: 'neutral' | 'success' | 'warning' }> = {
  DRAFT: { label: '초안', tone: 'neutral' },
  ACTIVE: { label: '활성', tone: 'success' },
  INACTIVE: { label: '비활성', tone: 'warning' },
}

function WorkflowRowMenu({
  workflow, projectId, projects, onOpenCompare, onOpenSetDefault,
}: {
  workflow: WorkflowListItem
  projectId: string | null
  // 전역 /workflows 목록(예: 표준 전처리 워크플로우)엔 projectId가 없어 복제
  // 대상 프로젝트를 고를 데가 없었다 — 여기서 직접 고를 수 있게 목록을 받는다.
  projects: { id: string; name: string }[]
  onOpenCompare: () => void
  onOpenSetDefault: () => void
}) {
  const navigate = useNavigate()
  const [menuPos, setMenuPos] = useState<{ top: number; right: number } | null>(null)
  const [showDuplicateTargets, setShowDuplicateTargets] = useState(false)
  const [showRenameInput, setShowRenameInput] = useState(false)
  const [renameValue, setRenameValue] = useState(workflow.name)
  const duplicateWorkflow = useDuplicateWorkflow()
  const updateStatus = useUpdateWorkflowStatus()
  const renameWorkflow = useRenameWorkflow()

  const closeMenu = () => {
    setMenuPos(null)
    setShowDuplicateTargets(false)
    setShowRenameInput(false)
    setRenameValue(workflow.name)
  }

  // 메뉴가 열려 있으면 Esc로 닫는다(바깥 클릭은 투명 막이 맡는다).
  const isMenuOpen = menuPos !== null
  useEffect(() => {
    if (!isMenuOpen) return undefined
    const handleKeyDown = (event: KeyboardEvent) => { if (event.key === 'Escape') closeMenu() }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
    // closeMenu는 매 렌더 새로 만들어지지만 상태 setter만 부르므로 열림 여부만 의존한다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isMenuOpen])

  const handleRename = async () => {
    const trimmed = renameValue.trim()
    if (!trimmed || trimmed === workflow.name) { closeMenu(); return }
    await renameWorkflow.mutateAsync({ workflowId: workflow.id, name: trimmed, projectId: projectId ?? '' })
    closeMenu()
  }

  const handleDuplicate = async (targetProjectId: string) => {
    closeMenu()
    const copy = await duplicateWorkflow.mutateAsync({ workflowId: workflow.id, projectId: targetProjectId })
    navigate(`/projects/${targetProjectId}/workflows/${copy.id}/edit`)
  }

  const runsPath = projectId
    ? `/projects/${projectId}/workflows/${workflow.id}/runs`
    : `/workflows/${workflow.id}/runs`

  const isStatusLocked = workflow.status !== 'INACTIVE' && workflow.is_system_default

  return (
    <div style={{ display: 'inline-block' }}>
      <IconButton
        label="더 보기"
        aria-expanded={menuPos !== null}
        onClick={(e) => {
          const rect = e.currentTarget.getBoundingClientRect()
          setMenuPos((prev) => (prev ? null : { top: rect.bottom + 4, right: window.innerWidth - rect.right }))
        }}
      >
        <MoreVertical size={14} aria-hidden="true" />
      </IconButton>
      {menuPos && (
        <>
          <div style={{ position: 'fixed', inset: 0, zIndex: 40 }} onClick={closeMenu} />
          <div className="pipeline-menu" style={{ top: menuPos.top, right: menuPos.right }}>
            {showRenameInput ? (
              <div className="pipeline-menu__rename">
                <Input
                  type="text"
                  aria-label="새 이름"
                  value={renameValue}
                  onChange={(e) => setRenameValue(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') handleRename()
                    if (e.key === 'Escape') closeMenu()
                  }}
                  controlSize="sm"
                  autoFocus
                />
                <div className="pipeline-menu__rename-actions">
                  <Button variant="ghost" size="sm" onClick={closeMenu}>취소</Button>
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={handleRename}
                    disabled={!renameValue.trim() || renameWorkflow.isPending}
                  >
                    저장
                  </Button>
                </div>
              </div>
            ) : (
              <>
                <button type="button" className="pipeline-menu__item" onClick={() => setShowRenameInput(true)}>
                  이름 변경
                </button>
                {!showDuplicateTargets ? (
                  <button
                    type="button"
                    className="pipeline-menu__item"
                    onClick={() => (projectId ? handleDuplicate(projectId) : setShowDuplicateTargets(true))}
                  >
                    복제{!projectId && ' ▸'}
                  </button>
                ) : (
                  <>
                    <div className="pipeline-menu__hint">어느 프로젝트로 복제할까요?</div>
                    {projects.length === 0 && (
                      <div className="pipeline-menu__hint">프로젝트가 없습니다.</div>
                    )}
                    {projects.map((p) => (
                      <button key={p.id} type="button" className="pipeline-menu__item" onClick={() => handleDuplicate(p.id)}>
                        {p.name}
                      </button>
                    ))}
                  </>
                )}
                <button
                  type="button"
                  className="pipeline-menu__item"
                  onClick={() => { closeMenu(); navigate(runsPath) }}
                >
                  실행 이력
                </button>
                <button
                  type="button"
                  className="pipeline-menu__item"
                  onClick={() => { closeMenu(); onOpenCompare() }}
                >
                  버전 비교
                </button>
                <button
                  type="button"
                  disabled={isStatusLocked || updateStatus.isPending}
                  className="pipeline-menu__item"
                  onClick={() => {
                    closeMenu()
                    const nextStatus = workflow.status === 'INACTIVE' ? 'ACTIVE' : 'INACTIVE'
                    updateStatus.mutate({ workflowId: workflow.id, status: nextStatus, projectId: projectId ?? '' })
                  }}
                  title={isStatusLocked ? '시스템 기본 워크플로우는 비활성화할 수 없습니다' : undefined}
                >
                  {workflow.status === 'INACTIVE' ? '활성화' : '비활성화'}
                </button>
                <button
                  type="button"
                  disabled={!projectId}
                  className="pipeline-menu__item"
                  onClick={() => { closeMenu(); onOpenSetDefault() }}
                  title={!projectId ? '어느 프로젝트의 컬렉션에 지정할지 알 수 없습니다 — 프로젝트 화면에서 지정하세요' : undefined}
                >
                  컬렉션 기본으로 지정
                </button>
              </>
            )}
          </div>
        </>
      )}
    </div>
  )
}

export default function WorkflowsPage() {
  const navigate = useNavigate()
  const { projectId } = useParams<{ projectId?: string }>()
  const isCrossProject = !projectId
  const [kindFilter, setKindFilter] = useState<'PREPROCESS' | 'ANALYSIS' | ''>('')
  const { data, isLoading, isError } = useWorkflows(projectId ?? null, kindFilter || undefined)
  const { data: projectsData } = useProjects()
  const createWorkflow = useCreateWorkflow()
  const deleteWorkflow = useDeleteWorkflow()
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [newName, setNewName] = useState('')
  const [newDescription, setNewDescription] = useState('')
  const [newKind, setNewKind] = useState<'PREPROCESS' | 'ANALYSIS'>('ANALYSIS')
  const [newProjectId, setNewProjectId] = useState('')
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null)
  const [compareWorkflow, setCompareWorkflow] = useState<WorkflowListItem | null>(null)
  const [setDefaultWorkflow, setSetDefaultWorkflow] = useState<WorkflowListItem | null>(null)

  const items = data?.items ?? []
  const countByStatus = (status: string) => items.filter((w) => w.status === status).length

  const handleCreate = async () => {
    const targetProjectId = projectId ?? newProjectId
    if (!targetProjectId || !newName.trim()) return
    const workflow = await createWorkflow.mutateAsync({
      project_id: targetProjectId, name: newName, description: newDescription || undefined, kind: newKind,
    })
    setShowCreateModal(false)
    setNewName('')
    setNewDescription('')
    setNewProjectId('')
    navigate(`/projects/${targetProjectId}/workflows/${workflow.id}/edit`)
  }

  const createFooter = (
    <>
      <Button variant="secondary" onClick={() => setShowCreateModal(false)}>취소</Button>
      <Button
        variant="primary"
        onClick={handleCreate}
        disabled={!newName.trim() || (isCrossProject && !newProjectId) || createWorkflow.isPending}
        icon={createWorkflow.isPending ? <Loader2 size={14} className="pipeline-spin" aria-hidden="true" /> : undefined}
      >
        생성
      </Button>
    </>
  )

  return (
    <Page>
      <PageHeader
        title="워크플로우"
        subtitle={isCrossProject
          ? '소속된 모든 프로젝트의 워크플로우입니다. 프로젝트별로 보려면 각 프로젝트의 워크플로우 탭을 이용하세요.'
          : undefined}
        actions={(
          <Button
            variant="primary"
            icon={<Plus size={16} aria-hidden="true" />}
            onClick={() => { setNewKind(kindFilter === 'PREPROCESS' ? 'PREPROCESS' : 'ANALYSIS'); setShowCreateModal(true) }}
          >
            워크플로우 생성
          </Button>
        )}
      />

      {!!items.length && (
        <StatStrip label="워크플로우 요약">
          <Stat label="전체" value={items.length} />
          <Stat label="활성" value={countByStatus('ACTIVE')} tone="success" />
          <Stat label="초안" value={countByStatus('DRAFT')} />
          <Stat label="비활성" value={countByStatus('INACTIVE')} tone={countByStatus('INACTIVE') > 0 ? 'warning' : 'default'} />
        </StatStrip>
      )}

      <Toolbar
        label="워크플로우 거르기"
        meta={data ? `${items.length}건` : undefined}
      >
        <Select
          id="workflow_kind_filter"
          name="workflow_kind_filter"
          aria-label="종류 거르기"
          controlSize="sm"
          value={kindFilter}
          onChange={(e) => setKindFilter(e.target.value as 'PREPROCESS' | 'ANALYSIS' | '')}
          style={{ width: 140 }}
        >
          <option value="">종류: 전체</option>
          <option value="PREPROCESS">전처리</option>
          <option value="ANALYSIS">분석</option>
        </Select>
      </Toolbar>

      <div style={{ padding: 'var(--space-4) var(--space-5)', display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
        {isLoading && <div style={{ color: 'var(--color-text-subtle)', fontSize: 'var(--text-sm)' }}>불러오는 중...</div>}
        {isError && <Alert tone="danger">워크플로우 목록을 불러오지 못했습니다.</Alert>}

        {!isLoading && data?.items.length === 0 && (
          <EmptyState
            icon={<GitBranch size={32} aria-hidden="true" />}
            title="등록된 워크플로우가 없습니다."
          />
        )}

        {!!data?.items.length && (
          <div className="ds-table-wrap">
            <table className="ds-table">
              <thead>
                <tr>
                  <th>이름</th>
                  {isCrossProject && <th>프로젝트</th>}
                  <th>종류</th>
                  <th className="ds-cell-num">버전</th>
                  <th>상태</th>
                  <th>기본 지정</th>
                  <th>수정자</th>
                  <th>수정일</th>
                  <th aria-label="작업" />
                </tr>
              </thead>
              <tbody>
                {data.items.map((workflow) => {
                  const badge = STATUS_BADGE[workflow.status] ?? { label: workflow.status, tone: 'neutral' as const }
                  const rowProjectId = workflow.project_id ?? projectId ?? null
                  const editPath = rowProjectId
                    ? `/projects/${rowProjectId}/workflows/${workflow.id}/edit`
                    : `/workflows/${workflow.id}/edit`
                  return (
                    <tr key={workflow.id}>
                      <td>
                        <button type="button" className="pipeline-name-link" onClick={() => navigate(editPath)}>
                          {workflow.is_system_default && '🔒 '}{workflow.name}
                        </button>
                      </td>
                      {isCrossProject && (
                        <td className="ds-cell-muted">
                          {workflow.is_system_default ? '전체' : (workflow.project_name ?? '-')}
                        </td>
                      )}
                      <td>
                        <Badge tone={workflow.kind === 'PREPROCESS' ? 'info' : 'neutral'}>
                          {KIND_LABELS[workflow.kind] ?? workflow.kind}
                        </Badge>
                      </td>
                      <td className="ds-cell-num ds-cell-muted pipeline-cell-mono">
                        {workflow.latest_version_number != null ? `v${workflow.latest_version_number}` : '-'}
                      </td>
                      <td>
                        <Badge tone={badge.tone} hasDot>{badge.label}</Badge>
                      </td>
                      <td>
                        {workflow.is_system_default ? (
                          <b>★ 시스템 기본</b>
                        ) : workflow.default_for_collection_count > 0 ? (
                          `컬렉션 ${workflow.default_for_collection_count}곳`
                        ) : (
                          <span className="ds-cell-muted">—</span>
                        )}
                      </td>
                      <td className="ds-cell-muted">
                        {workflow.is_system_default ? '시스템' : (workflow.created_by_username ?? '-')}
                      </td>
                      <td className="ds-cell-muted">
                        {new Date(workflow.updated_at).toLocaleDateString('ko-KR')}
                      </td>
                      <td style={{ textAlign: 'right' }}>
                        {confirmDeleteId === workflow.id ? (
                          <div className="pipeline-confirm">
                            <span className="pipeline-confirm__text">모든 버전·실행 이력이 함께 삭제됩니다</span>
                            <Button
                              variant="danger-solid"
                              size="sm"
                              disabled={deleteWorkflow.isPending}
                              onClick={async () => {
                                await deleteWorkflow.mutateAsync({ workflowId: workflow.id, projectId: rowProjectId ?? '' })
                                setConfirmDeleteId(null)
                              }}
                            >
                              확인
                            </Button>
                            <Button variant="ghost" size="sm" onClick={() => setConfirmDeleteId(null)}>취소</Button>
                          </div>
                        ) : (
                          <div style={{ display: 'inline-flex', gap: 'var(--space-1)', alignItems: 'center' }}>
                            <Button variant="ghost" size="sm" onClick={() => navigate(editPath)}>편집</Button>
                            {!workflow.is_system_default && (
                              <IconButton
                                tone="danger"
                                label="워크플로우 삭제"
                                onClick={() => setConfirmDeleteId(workflow.id)}
                              >
                                <Trash2 size={14} aria-hidden="true" />
                              </IconButton>
                            )}
                            <WorkflowRowMenu
                              workflow={workflow}
                              projectId={rowProjectId}
                              projects={projectsData?.items ?? []}
                              onOpenCompare={() => setCompareWorkflow(workflow)}
                              onOpenSetDefault={() => setSetDefaultWorkflow(workflow)}
                            />
                          </div>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {compareWorkflow && (
        <VersionCompareModal
          workflowId={compareWorkflow.id}
          workflowName={compareWorkflow.name}
          onClose={() => setCompareWorkflow(null)}
        />
      )}

      {setDefaultWorkflow && (setDefaultWorkflow.project_id ?? projectId) && (
        <SetCollectionDefaultModal
          projectId={(setDefaultWorkflow.project_id ?? projectId) as string}
          workflowId={setDefaultWorkflow.id}
          workflowName={setDefaultWorkflow.name}
          kind={setDefaultWorkflow.kind}
          isSystemDefault={setDefaultWorkflow.is_system_default}
          onClose={() => setSetDefaultWorkflow(null)}
        />
      )}

      <Modal
        isOpen={showCreateModal}
        title="새 워크플로우"
        onClose={() => setShowCreateModal(false)}
        footer={createFooter}
      >
        <div className="pipeline-modal-stack">
          <div className="pipeline-radios" role="radiogroup" aria-label="워크플로우 종류">
            <label>
              <input
                type="radio"
                id="new_workflow_kind_analysis"
                name="new_workflow_kind"
                checked={newKind === 'ANALYSIS'}
                onChange={() => setNewKind('ANALYSIS')}
              />
              분석 워크플로우
            </label>
            <label>
              <input
                type="radio"
                id="new_workflow_kind_preprocess"
                name="new_workflow_kind"
                checked={newKind === 'PREPROCESS'}
                onChange={() => setNewKind('PREPROCESS')}
              />
              전처리 워크플로우
            </label>
          </div>
          {isCrossProject && (
            <Field label="프로젝트">
              {(id) => (
                <Select
                  id={id}
                  value={newProjectId}
                  onChange={(e) => setNewProjectId(e.target.value)}
                  style={{ width: '100%' }}
                >
                  <option value="">프로젝트 선택</option>
                  {(projectsData?.items ?? []).map((project) => (
                    <option key={project.id} value={project.id}>{project.name}</option>
                  ))}
                </Select>
              )}
            </Field>
          )}
          <Field label="이름">
            {(id) => (
              <Input
                id={id}
                placeholder="예: 표준 전처리 워크플로우"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                autoFocus
              />
            )}
          </Field>
          <Field label="설명" hint="선택 사항입니다.">
            {(id) => (
              <Textarea
                id={id}
                placeholder="설명 (선택)"
                value={newDescription}
                onChange={(e) => setNewDescription(e.target.value)}
                rows={3}
              />
            )}
          </Field>
        </div>
      </Modal>
    </Page>
  )
}
