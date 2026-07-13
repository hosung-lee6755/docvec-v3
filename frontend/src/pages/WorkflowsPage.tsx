import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { GitBranch, Loader2, Plus, Trash2, X } from 'lucide-react'
import { useCreateWorkflow, useDeleteWorkflow, useWorkflows } from '../hooks/useWorkflows'

const STATUS_BADGE: Record<string, { label: string; className: string }> = {
  DRAFT: { label: '초안', className: 'bg-secondary' },
  ACTIVE: { label: '활성', className: 'bg-primary' },
  INACTIVE: { label: '비활성', className: 'bg-tertiary' },
}

export default function WorkflowsPage() {
  const navigate = useNavigate()
  const { projectId } = useParams<{ projectId?: string }>()
  const { data, isLoading, isError } = useWorkflows(projectId ?? null)
  const createWorkflow = useCreateWorkflow()
  const deleteWorkflow = useDeleteWorkflow()
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [newName, setNewName] = useState('')
  const [newDescription, setNewDescription] = useState('')
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null)

  const handleCreate = async () => {
    if (!projectId || !newName.trim()) return
    const workflow = await createWorkflow.mutateAsync({
      project_id: projectId, name: newName, description: newDescription || undefined,
    })
    setShowCreateModal(false)
    setNewName('')
    setNewDescription('')
    navigate(`/projects/${projectId}/workflows/${workflow.id}/edit`)
  }

  if (!projectId) {
    return <div style={{ padding: 'var(--space-4)' }}>프로젝트를 먼저 선택하세요.</div>
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--space-4)' }}>
        <h2 style={{ fontSize: 20, fontWeight: 700 }}>워크플로우</h2>
        <button
          type="button"
          onClick={() => setShowCreateModal(true)}
          className="krds-btn small primary"
          style={{ display: 'inline-flex', alignItems: 'center', gap: 'var(--space-2)' }}
        >
          <Plus size={16} /> 워크플로우 생성
        </button>
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
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
          <thead>
            <tr style={{ textAlign: 'left', borderBottom: '1px solid #e2e8f0' }}>
              <th style={{ padding: 'var(--space-2)', color: '#94a3b8', fontSize: 12, fontWeight: 700, textTransform: 'uppercase' }}>워크플로우명</th>
              <th style={{ padding: 'var(--space-2)', color: '#94a3b8', fontSize: 12, fontWeight: 700, textTransform: 'uppercase' }}>설명</th>
              <th style={{ padding: 'var(--space-2)', color: '#94a3b8', fontSize: 12, fontWeight: 700, textTransform: 'uppercase' }}>상태</th>
              <th style={{ padding: 'var(--space-2)', color: '#94a3b8', fontSize: 12, fontWeight: 700, textTransform: 'uppercase' }}>생성일</th>
              <th style={{ padding: 'var(--space-2)' }} />
            </tr>
          </thead>
          <tbody>
            {data.items.map((workflow) => {
              const badge = STATUS_BADGE[workflow.status] ?? { label: workflow.status, className: 'bg-secondary' }
              const editPath = `/projects/${projectId}/workflows/${workflow.id}/edit`
              return (
                <tr key={workflow.id} style={{ borderBottom: '1px solid #e2e8f0' }}>
                  <td
                    style={{ padding: 'var(--space-2)', fontWeight: 600, cursor: 'pointer', color: 'var(--color-accent)' }}
                    onClick={() => navigate(editPath)}
                  >
                    {workflow.name}
                  </td>
                  <td style={{ padding: 'var(--space-2)', color: '#94a3b8' }}>
                    {workflow.description || '-'}
                  </td>
                  <td style={{ padding: 'var(--space-2)' }}>
                    <span className={`krds-badge small ${badge.className}`}>{badge.label}</span>
                  </td>
                  <td style={{ padding: 'var(--space-2)', color: '#94a3b8' }}>
                    {new Date(workflow.created_at).toLocaleDateString('ko-KR')}
                  </td>
                  <td style={{ padding: 'var(--space-2)', textAlign: 'right' }}>
                    {confirmDeleteId === workflow.id ? (
                      <div style={{ display: 'inline-flex', gap: 'var(--space-2)', alignItems: 'center' }}>
                        <span style={{ fontSize: 12, color: '#dc2626' }}>모든 버전·실행 이력이 함께 삭제됩니다</span>
                        <button
                          type="button"
                          onClick={async () => {
                            if (!projectId) return
                            await deleteWorkflow.mutateAsync({ workflowId: workflow.id, projectId })
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
                      <div style={{ display: 'inline-flex', gap: 'var(--space-1)' }}>
                        <button
                          type="button"
                          onClick={() => navigate(editPath)}
                          className="krds-btn xsmall text"
                        >
                          편집
                        </button>
                        <button
                          type="button"
                          onClick={() => setConfirmDeleteId(workflow.id)}
                          className="krds-btn xsmall text"
                          title="삭제"
                          aria-label="워크플로우 삭제"
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
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
                    <input
                      placeholder="이름"
                      value={newName}
                      onChange={(e) => setNewName(e.target.value)}
                      className="krds-input"
                      autoFocus
                    />
                    <textarea
                      placeholder="설명 (선택)"
                      value={newDescription}
                      onChange={(e) => setNewDescription(e.target.value)}
                      className="krds-input"
                      rows={3}
                    />
                    <div className="modal-btn btn-wrap">
                      <button type="button" className="krds-btn medium secondary" onClick={() => setShowCreateModal(false)}>
                        취소
                      </button>
                      <button
                        type="button"
                        onClick={handleCreate}
                        disabled={!newName.trim() || createWorkflow.isPending}
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
