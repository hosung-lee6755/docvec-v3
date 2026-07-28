import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { GitBranch, Loader2, MoreVertical, Plus, Trash2, X } from 'lucide-react'
import {
  useCreateWorkflow, useDeleteWorkflow, useDuplicateWorkflow, useRenameWorkflow, useUpdateWorkflowStatus, useWorkflows,
  type WorkflowListItem,
} from '../hooks/useWorkflows'
import { useProjects } from '../hooks/useProjects'
import VersionCompareModal from '../components/workflow/VersionCompareModal'
import SetCollectionDefaultModal from '../components/workflow/SetCollectionDefaultModal'

const KIND_LABELS: Record<string, string> = { PREPROCESS: '전처리', ANALYSIS: '분석' }

const STATUS_BADGE: Record<string, { label: string; className: string }> = {
  DRAFT: { label: '초안', className: 'bg-secondary' },
  ACTIVE: { label: '활성', className: 'bg-primary' },
  INACTIVE: { label: '비활성', className: 'bg-tertiary' },
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

  return (
    <div style={{ display: 'inline-block' }}>
      <button
        type="button"
        onClick={(e) => {
          const rect = e.currentTarget.getBoundingClientRect()
          setMenuPos((prev) => (prev ? null : { top: rect.bottom + 4, right: window.innerWidth - rect.right }))
        }}
        className="krds-btn xsmall text icon-btn"
        aria-label="더 보기"
      >
        <MoreVertical size={14} />
      </button>
      {menuPos && (
        <>
          <div style={{ position: 'fixed', inset: 0, zIndex: 40 }} onClick={closeMenu} />
          <div style={{
            position: 'fixed', top: menuPos.top, right: menuPos.right, zIndex: 50,
            background: '#fff', border: '1px solid #e2e8f0', borderRadius: 'var(--radius-sm)',
            boxShadow: '0 4px 12px rgba(0,0,0,0.15)', minWidth: 180, maxHeight: 280, overflowY: 'auto',
            display: 'flex', flexDirection: 'column',
          }}>
            {showRenameInput ? (
              <div style={{ padding: 8, display: 'flex', flexDirection: 'column', gap: 6 }}>
                <input
                  type="text"
                  value={renameValue}
                  onChange={(e) => setRenameValue(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') handleRename()
                    if (e.key === 'Escape') closeMenu()
                  }}
                  className="krds-input"
                  style={{ fontSize: 13, padding: '4px 6px', width: '100%' }}
                  autoFocus
                />
                <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
                  <button type="button" onClick={closeMenu} className="krds-btn text xsmall">취소</button>
                  <button
                    type="button"
                    onClick={handleRename}
                    disabled={!renameValue.trim() || renameWorkflow.isPending}
                    className="krds-btn primary xsmall"
                  >
                    저장
                  </button>
                </div>
              </div>
            ) : (
              <>
                <button
                  type="button"
                  onClick={() => setShowRenameInput(true)}
                  className="krds-btn text xsmall"
                  style={{ justifyContent: 'flex-start', padding: '8px 12px' }}
                >
                  이름 변경
                </button>
                {!showDuplicateTargets ? (
                  <button
                    type="button"
                    onClick={() => (projectId ? handleDuplicate(projectId) : setShowDuplicateTargets(true))}
                    className="krds-btn text xsmall"
                    style={{ justifyContent: 'flex-start', padding: '8px 12px' }}
                  >
                    복제{!projectId && ' ▸'}
                  </button>
                ) : (
                  <>
                    <div style={{ padding: '6px 12px', fontSize: 11, color: 'var(--color-text-muted)', borderBottom: '1px solid #e2e8f0' }}>
                      어느 프로젝트로 복제할까요?
                    </div>
                    {projects.length === 0 && (
                      <div style={{ padding: '8px 12px', fontSize: 12, color: 'var(--color-text-muted)' }}>
                        프로젝트가 없습니다.
                      </div>
                    )}
                    {projects.map((p) => (
                      <button
                        key={p.id}
                        type="button"
                        onClick={() => handleDuplicate(p.id)}
                        className="krds-btn text xsmall"
                        style={{ justifyContent: 'flex-start', padding: '8px 12px' }}
                      >
                        {p.name}
                      </button>
                    ))}
                  </>
                )}
                <button
                  type="button"
                  onClick={() => { closeMenu(); navigate(runsPath) }}
                  className="krds-btn text xsmall"
                  style={{ justifyContent: 'flex-start', padding: '8px 12px' }}
                >
                  실행 이력
                </button>
            <button
              type="button"
              onClick={() => { closeMenu(); onOpenCompare() }}
              className="krds-btn text xsmall"
              style={{ justifyContent: 'flex-start', padding: '8px 12px' }}
            >
              버전 비교
            </button>
            <button
              type="button"
              disabled={(workflow.status !== 'INACTIVE' && workflow.is_system_default) || updateStatus.isPending}
              onClick={() => {
                closeMenu()
                const nextStatus = workflow.status === 'INACTIVE' ? 'ACTIVE' : 'INACTIVE'
                updateStatus.mutate({ workflowId: workflow.id, status: nextStatus, projectId: projectId ?? '' })
              }}
              className="krds-btn text xsmall"
              style={{ justifyContent: 'flex-start', padding: '8px 12px' }}
              title={workflow.status !== 'INACTIVE' && workflow.is_system_default ? '시스템 기본 워크플로우는 비활성화할 수 없습니다' : undefined}
            >
              {workflow.status === 'INACTIVE' ? '활성화' : '비활성화'}
            </button>
            <button
              type="button"
              onClick={() => { closeMenu(); onOpenSetDefault() }}
              disabled={!projectId}
              className="krds-btn text xsmall"
              style={{ justifyContent: 'flex-start', padding: '8px 12px' }}
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

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--space-4)' }}>
        <div>
          <h2 style={{ fontSize: 18, fontWeight: 700 }}>워크플로우</h2>
          {isCrossProject && (
            <p style={{ fontSize: 12, color: 'var(--color-text-muted)', margin: '2px 0 0' }}>
              소속된 모든 프로젝트의 워크플로우입니다. 프로젝트별로 보려면 각 프로젝트의 워크플로우 탭을 이용하세요.
            </p>
          )}
        </div>
        <div style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'center' }}>
          <select
            id="workflow_kind_filter"
            name="workflow_kind_filter"
            className="krds-form-select small"
            value={kindFilter}
            onChange={(e) => setKindFilter(e.target.value as 'PREPROCESS' | 'ANALYSIS' | '')}
            style={{ width: 140 }}
          >
            <option value="">종류: 전체</option>
            <option value="PREPROCESS">전처리</option>
            <option value="ANALYSIS">분석</option>
          </select>
          <button
            type="button"
            onClick={() => { setNewKind(kindFilter === 'PREPROCESS' ? 'PREPROCESS' : 'ANALYSIS'); setShowCreateModal(true) }}
            className="krds-btn small primary"
            style={{ display: 'inline-flex', alignItems: 'center', gap: 'var(--space-2)' }}
          >
            <Plus size={16} /> 워크플로우 생성
          </button>
        </div>
      </div>

      {isLoading && <div style={{ color: '#94a3b8', fontSize: 14 }}>불러오는 중...</div>}
      {isError && <div style={{ color: '#dc2626', fontSize: 14 }}>워크플로우 목록을 불러오지 못했습니다.</div>}

      {!isLoading && data?.items.length === 0 && (
        <div style={{
          padding: 'var(--space-8)', textAlign: 'center', color: '#94a3b8',
          border: '1px dashed #e2e8f0', borderRadius: 'var(--radius-lg)',
        }}>
          <GitBranch size={32} style={{ marginBottom: 'var(--space-2)' }} />
          <div>등록된 워크플로우가 없습니다.</div>
        </div>
      )}

      {!!data?.items.length && (
        <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
          <thead>
            <tr style={{ textAlign: 'left', borderBottom: '1px solid #e2e8f0' }}>
              <th style={{ padding: 'var(--space-2)', color: '#94a3b8', fontSize: 12, fontWeight: 700, textTransform: 'uppercase' }}>이름</th>
              {isCrossProject && (
                <th style={{ padding: 'var(--space-2)', color: '#94a3b8', fontSize: 12, fontWeight: 700, textTransform: 'uppercase' }}>프로젝트</th>
              )}
              <th style={{ padding: 'var(--space-2)', color: '#94a3b8', fontSize: 12, fontWeight: 700, textTransform: 'uppercase' }}>종류</th>
              <th style={{ padding: 'var(--space-2)', color: '#94a3b8', fontSize: 12, fontWeight: 700, textTransform: 'uppercase' }}>버전</th>
              <th style={{ padding: 'var(--space-2)', color: '#94a3b8', fontSize: 12, fontWeight: 700, textTransform: 'uppercase' }}>상태</th>
              <th style={{ padding: 'var(--space-2)', color: '#94a3b8', fontSize: 12, fontWeight: 700, textTransform: 'uppercase' }}>기본 지정</th>
              <th style={{ padding: 'var(--space-2)', color: '#94a3b8', fontSize: 12, fontWeight: 700, textTransform: 'uppercase' }}>수정자</th>
              <th style={{ padding: 'var(--space-2)', color: '#94a3b8', fontSize: 12, fontWeight: 700, textTransform: 'uppercase' }}>수정일</th>
              <th style={{ padding: 'var(--space-2)' }} />
            </tr>
          </thead>
          <tbody>
            {data.items.map((workflow) => {
              const badge = STATUS_BADGE[workflow.status] ?? { label: workflow.status, className: 'bg-secondary' }
              const rowProjectId = workflow.project_id ?? projectId ?? null
              const editPath = rowProjectId
                ? `/projects/${rowProjectId}/workflows/${workflow.id}/edit`
                : `/workflows/${workflow.id}/edit`
              return (
                <tr key={workflow.id} style={{ borderBottom: '1px solid #e2e8f0' }}>
                  <td
                    style={{ padding: 'var(--space-2)', fontWeight: 600, cursor: 'pointer', color: 'var(--color-accent)' }}
                    onClick={() => navigate(editPath)}
                  >
                    {workflow.is_system_default && '🔒 '}{workflow.name}
                  </td>
                  {isCrossProject && (
                    <td style={{ padding: 'var(--space-2)', color: 'var(--color-text-muted)' }}>
                      {workflow.is_system_default ? '전체' : (workflow.project_name ?? '-')}
                    </td>
                  )}
                  <td style={{ padding: 'var(--space-2)' }}>
                    <span className={`krds-badge small ${workflow.kind === 'PREPROCESS' ? 'bg-primary' : 'bg-secondary'}`}>
                      {KIND_LABELS[workflow.kind] ?? workflow.kind}
                    </span>
                  </td>
                  <td style={{ padding: 'var(--space-2)', color: '#94a3b8', fontFamily: 'monospace' }}>
                    {workflow.latest_version_number != null ? `v${workflow.latest_version_number}` : '-'}
                  </td>
                  <td style={{ padding: 'var(--space-2)' }}>
                    <span className={`krds-badge small ${badge.className}`}>{badge.label}</span>
                  </td>
                  <td style={{ padding: 'var(--space-2)' }}>
                    {workflow.is_system_default ? (
                      <b>★ 시스템 기본</b>
                    ) : workflow.default_for_collection_count > 0 ? (
                      `컬렉션 ${workflow.default_for_collection_count}곳`
                    ) : (
                      <span style={{ color: '#94a3b8' }}>—</span>
                    )}
                  </td>
                  <td style={{ padding: 'var(--space-2)', color: '#94a3b8' }}>
                    {workflow.is_system_default ? '시스템' : (workflow.created_by_username ?? '-')}
                  </td>
                  <td style={{ padding: 'var(--space-2)', color: '#94a3b8' }}>
                    {new Date(workflow.updated_at).toLocaleDateString('ko-KR')}
                  </td>
                  <td style={{ padding: 'var(--space-2)', textAlign: 'right' }}>
                    {confirmDeleteId === workflow.id ? (
                      <div style={{ display: 'inline-flex', gap: 'var(--space-2)', alignItems: 'center' }}>
                        <span style={{ fontSize: 12, color: '#dc2626' }}>모든 버전·실행 이력이 함께 삭제됩니다</span>
                        <button
                          type="button"
                          onClick={async () => {
                            await deleteWorkflow.mutateAsync({ workflowId: workflow.id, projectId: rowProjectId ?? '' })
                            setConfirmDeleteId(null)
                          }}
                          disabled={deleteWorkflow.isPending}
                          className="krds-btn xsmall primary"
                        >확인</button>
                        <button
                          type="button"
                          onClick={() => setConfirmDeleteId(null)}
                          className="krds-btn xsmall secondary"
                        >취소</button>
                      </div>
                    ) : (
                      <div style={{ display: 'inline-flex', gap: 'var(--space-1)', alignItems: 'center' }}>
                        <button
                          type="button"
                          onClick={() => navigate(editPath)}
                          className="krds-btn xsmall text"
                        >
                          편집
                        </button>
                        {!workflow.is_system_default && (
                          <button
                            type="button"
                            onClick={() => setConfirmDeleteId(workflow.id)}
                            className="krds-btn xsmall text icon-btn danger"
                            title="삭제"
                            aria-label="워크플로우 삭제"
                          >
                            <Trash2 size={14} />
                          </button>
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

      {showCreateModal && (
        <div style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 50,
        }}>
          <section className="krds-modal fade shown in" role="dialog">
            <div className="modal-dialog modal-md">
              <div className="modal-content">
                <div className="modal-header">
                  <h2 className="modal-title">새 워크플로우</h2>
                </div>
                <div className="modal-conts">
                  <div className="conts-area" style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
                    <div style={{ display: 'flex', gap: 'var(--space-4)' }}>
                      <div className="krds-form-check" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        <input
                          type="radio"
                          id="new_workflow_kind_analysis"
                          name="new_workflow_kind"
                          checked={newKind === 'ANALYSIS'}
                          onChange={() => setNewKind('ANALYSIS')}
                        />
                        <label htmlFor="new_workflow_kind_analysis" style={{ fontSize: 13 }}>분석 워크플로우</label>
                      </div>
                      <div className="krds-form-check" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        <input
                          type="radio"
                          id="new_workflow_kind_preprocess"
                          name="new_workflow_kind"
                          checked={newKind === 'PREPROCESS'}
                          onChange={() => setNewKind('PREPROCESS')}
                        />
                        <label htmlFor="new_workflow_kind_preprocess" style={{ fontSize: 13 }}>전처리 워크플로우</label>
                      </div>
                    </div>
                    {isCrossProject && (
                      <div className="form-group">
                        <div className="form-tit"><label htmlFor="new_workflow_project">프로젝트</label></div>
                        <div className="form-conts">
                          <select
                            id="new_workflow_project"
                            className="krds-form-select small"
                            value={newProjectId}
                            onChange={(e) => setNewProjectId(e.target.value)}
                            style={{ width: '100%' }}
                          >
                            <option value="">프로젝트 선택</option>
                            {(projectsData?.items ?? []).map((project) => (
                              <option key={project.id} value={project.id}>{project.name}</option>
                            ))}
                          </select>
                        </div>
                      </div>
                    )}
                    <input
                      placeholder="예: 표준 전처리 워크플로우"
                      value={newName}
                      onChange={(e) => setNewName(e.target.value)}
                      className="krds-input small"
                      autoFocus
                    />
                    <textarea
                      placeholder="설명 (선택)"
                      value={newDescription}
                      onChange={(e) => setNewDescription(e.target.value)}
                      className="krds-input small"
                      rows={3}
                    />
                    <div className="modal-btn btn-wrap">
                      <button type="button" className="krds-btn medium secondary" onClick={() => setShowCreateModal(false)}>
                        취소
                      </button>
                      <button
                        type="button"
                        onClick={handleCreate}
                        disabled={!newName.trim() || (isCrossProject && !newProjectId) || createWorkflow.isPending}
                        className="krds-btn medium primary"
                        style={{ display: 'inline-flex', alignItems: 'center', gap: 'var(--space-2)' }}
                      >
                        {createWorkflow.isPending && <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} />}
                        생성
                      </button>
                    </div>
                  </div>
                </div>
                <button type="button" className="krds-btn medium icon btn-close close-modal" onClick={() => setShowCreateModal(false)}>
                  <span className="sr-only">닫기</span>
                  <X size={20} />
                </button>
              </div>
            </div>
            <div className="modal-back"></div>
          </section>
        </div>
      )}
      <style>{`@keyframes spin { to { transform: rotate(360deg) } }`}</style>
    </div>
  )
}
