import { useState } from 'react'
import { Outlet, useNavigate, useParams } from 'react-router-dom'
import { Plus, Pencil, Trash2, Check, X, Loader2 } from 'lucide-react'
import {
  useProjects,
  useCreateProject,
  useUpdateProject,
  useDeleteProject,
  type Project,
} from '../hooks/useProjects'

export default function ProjectsPage() {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()

  return (
    <div style={{ display: 'flex', gap: 'var(--space-6)', height: 'calc(100vh - var(--space-8) * 2)' }}>
      <ProjectSidebar
        activeId={projectId ?? null}
        onSelect={(id) => navigate(`/projects/${id}`)}
        onNew={() => navigate('/projects')}
      />
      <div style={{ flex: '1 1 auto', minWidth: 0, overflowY: 'auto' }}>
        {projectId ? <Outlet /> : <NewProjectForm onCreated={(id) => navigate(`/projects/${id}`)} />}
      </div>
    </div>
  )
}

function ProjectSidebar({
  activeId, onSelect, onNew,
}: { activeId: string | null; onSelect: (id: string) => void; onNew: () => void }) {
  const { data } = useProjects()
  const updateProject = useUpdateProject()
  const deleteProject = useDeleteProject()
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editingName, setEditingName] = useState('')
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null)

  const startEdit = (p: Project) => {
    setEditingId(p.id)
    setEditingName(p.name)
  }
  const commitEdit = () => {
    const name = editingName.trim()
    if (editingId && name) updateProject.mutate({ id: editingId, name })
    setEditingId(null)
  }
  const handleDelete = (id: string) => {
    deleteProject.mutate(id)
    setConfirmDeleteId(null)
    if (id === activeId) onNew()
  }

  return (
    <div style={{
      width: 260, flexShrink: 0, display: 'flex', flexDirection: 'column',
      borderRight: '1px solid var(--color-border)', paddingRight: 'var(--space-4)',
    }}>
      <button type="button" onClick={onNew} className="krds-btn small primary"
        style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', marginBottom: 'var(--space-4)' }}>
        <Plus size={16} /> 새 프로젝트
      </button>

      <div style={{ flex: '1 1 auto', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 2 }}>
        {data?.items.map((p) => (
          <div
            key={p.id}
            onClick={() => editingId !== p.id && onSelect(p.id)}
            style={{
              display: 'flex', alignItems: 'center', gap: 'var(--space-2)',
              padding: 'var(--space-2) var(--space-3)', borderRadius: 'var(--radius-md, 8px)',
              cursor: 'pointer', background: p.id === activeId ? '#eff6ff' : 'transparent',
              color: p.id === activeId ? '#1d4ed8' : '#334155', fontSize: 13,
            }}
          >
            {editingId === p.id ? (
              <>
                <input
                  autoFocus
                  value={editingName}
                  onChange={(e) => setEditingName(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') commitEdit()
                    if (e.key === 'Escape') setEditingId(null)
                  }}
                  onClick={(e) => e.stopPropagation()}
                  className="krds-input small"
                  style={{ flex: '1 1 auto', minWidth: 0 }}
                />
                <button type="button" onClick={(e) => { e.stopPropagation(); commitEdit() }}
                  style={{ color: '#16a34a', flexShrink: 0 }} title="저장">
                  <Check size={14} />
                </button>
                <button type="button" onClick={(e) => { e.stopPropagation(); setEditingId(null) }}
                  style={{ color: '#64748b', flexShrink: 0 }} title="취소">
                  <X size={14} />
                </button>
              </>
            ) : confirmDeleteId === p.id ? (
              <>
                <span style={{ flex: '1 1 auto', fontSize: 12, color: '#dc2626' }}>삭제할까요?</span>
                <button type="button" onClick={(e) => { e.stopPropagation(); handleDelete(p.id) }}
                  style={{ color: '#dc2626', flexShrink: 0 }} title="삭제 확인">
                  <Check size={14} />
                </button>
                <button type="button" onClick={(e) => { e.stopPropagation(); setConfirmDeleteId(null) }}
                  style={{ color: '#64748b', flexShrink: 0 }} title="취소">
                  <X size={14} />
                </button>
              </>
            ) : (
              <>
                <span style={{ flex: '1 1 auto', minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {p.name}
                </span>
                <span style={{ fontSize: 11, color: '#94a3b8', flexShrink: 0 }}>{p.collection_count}</span>
                {p.is_owner && (
                  <>
                    <button type="button" onClick={(e) => { e.stopPropagation(); startEdit(p) }}
                      style={{ color: '#94a3b8', flexShrink: 0 }} title="이름 변경">
                      <Pencil size={13} />
                    </button>
                    <button type="button" onClick={(e) => { e.stopPropagation(); setConfirmDeleteId(p.id) }}
                      style={{ color: '#94a3b8', flexShrink: 0 }} title="삭제">
                      <Trash2 size={13} />
                    </button>
                  </>
                )}
              </>
            )}
          </div>
        ))}
        {!data?.items.length && (
          <p style={{ fontSize: 13, color: 'var(--color-text-muted)', padding: 'var(--space-3)' }}>
            아직 프로젝트가 없습니다.
          </p>
        )}
      </div>
    </div>
  )
}

function NewProjectForm({ onCreated }: { onCreated: (id: string) => void }) {
  const createProject = useCreateProject()
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim()) return
    const project = await createProject.mutateAsync({
      name: name.trim(),
      description: description.trim() || undefined,
    })
    onCreated(project.id)
  }

  return (
    <div style={{ maxWidth: 480 }}>
      <h1 style={{ fontSize: 20, fontWeight: 700, marginBottom: 'var(--space-2)' }}>새 프로젝트 만들기</h1>
      <p style={{ fontSize: 13, color: 'var(--color-text-muted)', marginBottom: 'var(--space-6)' }}>
        프로젝트를 만들면 그 안에 프로젝트만의 컬렉션·문서·검색·채팅 공간이 생기고, 초대된 멤버는
        이 공간에 자동으로 접근할 수 있습니다. 특정 컬렉션만 일부 멤버를 제외하고 싶을 때는
        컬렉션 화면의 공유 설정에서 개별 제한할 수 있습니다.
      </p>
      <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="프로젝트 이름"
          className="krds-input"
          required
        />
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="설명 (선택 사항)"
          className="krds-input"
          rows={3}
        />
        <button
          type="submit"
          disabled={createProject.isPending || !name.trim()}
          className="krds-btn medium primary"
          style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', justifyContent: 'center', alignSelf: 'flex-start' }}
        >
          {createProject.isPending && <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} />}
          만들기
        </button>
      </form>
      <style>{`@keyframes spin { to { transform: rotate(360deg) } }`}</style>
    </div>
  )
}
