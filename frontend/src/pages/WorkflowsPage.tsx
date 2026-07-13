import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { GitBranch, Plus } from 'lucide-react'
import { useCreateWorkflow, useWorkflows } from '../hooks/useWorkflows'

const STATUS_LABELS: Record<string, string> = {
  DRAFT: '초안', ACTIVE: '활성', INACTIVE: '비활성',
}

export default function WorkflowsPage() {
  const navigate = useNavigate()
  const { projectId } = useParams<{ projectId?: string }>()
  const { data, isLoading, isError } = useWorkflows(projectId ?? null)
  const createWorkflow = useCreateWorkflow()
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [newName, setNewName] = useState('')
  const [newDescription, setNewDescription] = useState('')

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
          style={{
            display: 'inline-flex', alignItems: 'center', gap: 'var(--space-2)',
            padding: 'var(--space-2) var(--space-3)', borderRadius: 'var(--radius-md)',
            background: 'var(--color-accent)', color: '#fff', border: 'none', cursor: 'pointer',
          }}
        >
          <Plus size={16} /> 워크플로우 생성
        </button>
      </div>

      {isLoading && <div>불러오는 중...</div>}
      {isError && <div>워크플로우 목록을 불러오지 못했습니다.</div>}

      {!isLoading && data?.items.length === 0 && (
        <div style={{ padding: 'var(--space-6)', textAlign: 'center', color: 'var(--color-text-muted)' }}>
          <GitBranch size={32} style={{ marginBottom: 'var(--space-2)' }} />
          <div>등록된 워크플로우가 없습니다.</div>
        </div>
      )}

      {!!data?.items.length && (
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
          <thead>
            <tr style={{ textAlign: 'left', borderBottom: '1px solid var(--color-border)' }}>
              <th style={{ padding: 'var(--space-2)' }}>워크플로우명</th>
              <th style={{ padding: 'var(--space-2)' }}>설명</th>
              <th style={{ padding: 'var(--space-2)' }}>상태</th>
              <th style={{ padding: 'var(--space-2)' }}>생성일</th>
              <th style={{ padding: 'var(--space-2)' }} />
            </tr>
          </thead>
          <tbody>
            {data.items.map((workflow) => (
              <tr key={workflow.id} style={{ borderBottom: '1px solid var(--color-border)' }}>
                <td style={{ padding: 'var(--space-2)' }}>{workflow.name}</td>
                <td style={{ padding: 'var(--space-2)', color: 'var(--color-text-muted)' }}>
                  {workflow.description || '-'}
                </td>
                <td style={{ padding: 'var(--space-2)' }}>{STATUS_LABELS[workflow.status] ?? workflow.status}</td>
                <td style={{ padding: 'var(--space-2)' }}>
                  {new Date(workflow.created_at).toLocaleDateString('ko-KR')}
                </td>
                <td style={{ padding: 'var(--space-2)', textAlign: 'right' }}>
                  <button
                    type="button"
                    onClick={() => navigate(`/projects/${projectId}/workflows/${workflow.id}/edit`)}
                    style={{ fontSize: 13, color: 'var(--color-accent)', background: 'none', border: 'none', cursor: 'pointer' }}
                  >
                    편집
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {showCreateModal && (
        <div style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.4)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 50,
        }}>
          <div style={{ background: 'var(--color-surface)', padding: 'var(--space-5)', borderRadius: 'var(--radius-md)', width: 400 }}>
            <h3 style={{ marginBottom: 'var(--space-3)' }}>새 워크플로우</h3>
            <input
              placeholder="이름"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              style={{ width: '100%', padding: 'var(--space-2)', marginBottom: 'var(--space-2)', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-md)' }}
            />
            <textarea
              placeholder="설명 (선택)"
              value={newDescription}
              onChange={(e) => setNewDescription(e.target.value)}
              style={{ width: '100%', padding: 'var(--space-2)', marginBottom: 'var(--space-3)', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-md)' }}
            />
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 'var(--space-2)' }}>
              <button type="button" onClick={() => setShowCreateModal(false)}>취소</button>
              <button type="button" onClick={handleCreate} disabled={!newName.trim() || createWorkflow.isPending}>
                생성
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
