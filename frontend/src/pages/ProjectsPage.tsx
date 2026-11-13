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
import { useAuthStore } from '../store/authStore'
import { Button, ErrorAlert, Field, IconButton, Input, Page, PageBody, PageHeader, Textarea } from '../components/ui'

export default function ProjectsPage() {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()

  return (
    <div className="ds-page" style={{ flexDirection: 'row', height: '100%' }}>
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

function ProjectRowActions({
  project, isAdmin, onStartEdit, onAskDelete,
}: { project: Project; isAdmin: boolean; onStartEdit: () => void; onAskDelete: () => void }) {
  return (
    <span style={{ display: 'inline-flex', gap: 'var(--space-1)', flexShrink: 0 }}>
      {project.is_owner && (
        <IconButton label="이름 변경" onClick={(e) => { e.stopPropagation(); onStartEdit() }}>
          <Pencil size={13} aria-hidden="true" />
        </IconButton>
      )}
      {(project.is_owner || isAdmin) && (
        <IconButton label="삭제" tone="danger" onClick={(e) => { e.stopPropagation(); onAskDelete() }}>
          <Trash2 size={13} aria-hidden="true" />
        </IconButton>
      )}
    </span>
  )
}

function ProjectSidebar({
  activeId, onSelect, onNew,
}: { activeId: string | null; onSelect: (id: string) => void; onNew: () => void }) {
  const { data, isError, error, refetch } = useProjects()
  const updateProject = useUpdateProject()
  const deleteProject = useDeleteProject()
  const isAdmin = useAuthStore((s) => s.user?.role === 'admin')
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
    <nav
      aria-label="프로젝트 목록"
      style={{
        width: 264, flexShrink: 0, display: 'flex', flexDirection: 'column',
        borderRight: '1px solid var(--color-border-subtle)', padding: 'var(--space-4)', minHeight: 0,
      }}
    >
      <Button variant="primary" size="sm" onClick={onNew} icon={<Plus size={14} aria-hidden="true" />}
        style={{ marginBottom: 'var(--space-4)', alignSelf: 'stretch' }}>
        새 프로젝트
      </Button>

      {isError && <ErrorAlert error={error} message="프로젝트 목록을 불러오지 못했습니다." onRetry={() => refetch()} />}
      {updateProject.isError && <ErrorAlert error={updateProject.error} message="프로젝트 이름을 바꾸지 못했습니다." />}
      {deleteProject.isError && <ErrorAlert error={deleteProject.error} message="프로젝트를 삭제하지 못했습니다." />}

      <div style={{ flex: '1 1 auto', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 2 }}>
        {data?.items.map((p) => {
          const isActive = p.id === activeId
          return (
            <div
              key={p.id}
              onClick={() => editingId !== p.id && onSelect(p.id)}
              style={{
                display: 'flex', alignItems: 'center', gap: 'var(--space-2)',
                padding: 'var(--space-2) var(--space-3)', borderRadius: 'var(--radius-md)',
                cursor: 'pointer', fontSize: 'var(--text-sm)',
                background: isActive ? 'var(--color-primary-subtle)' : 'transparent',
                color: isActive ? 'var(--color-primary)' : 'var(--color-text)',
                fontWeight: isActive ? 600 : 400,
              }}
            >
              {editingId === p.id ? (
                <>
                  <Input
                    autoFocus
                    aria-label="프로젝트 이름"
                    value={editingName}
                    onChange={(e) => setEditingName(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') commitEdit()
                      if (e.key === 'Escape') setEditingId(null)
                    }}
                    onClick={(e) => e.stopPropagation()}
                    controlSize="sm"
                    style={{ flex: '1 1 auto', minWidth: 0 }}
                  />
                  <IconButton label="저장" onClick={(e) => { e.stopPropagation(); commitEdit() }}>
                    <Check size={14} aria-hidden="true" />
                  </IconButton>
                  <IconButton label="취소" onClick={(e) => { e.stopPropagation(); setEditingId(null) }}>
                    <X size={14} aria-hidden="true" />
                  </IconButton>
                </>
              ) : confirmDeleteId === p.id ? (
                <>
                  <span style={{ flex: '1 1 auto', fontSize: 'var(--text-xs)', color: 'var(--color-danger)' }}>삭제할까요?</span>
                  <IconButton label="삭제 확인" tone="danger" onClick={(e) => { e.stopPropagation(); handleDelete(p.id) }}>
                    <Check size={14} aria-hidden="true" />
                  </IconButton>
                  <IconButton label="취소" onClick={(e) => { e.stopPropagation(); setConfirmDeleteId(null) }}>
                    <X size={14} aria-hidden="true" />
                  </IconButton>
                </>
              ) : (
                <>
                  {/* 행 전체 클릭과 별개로, 키보드와 화면 낭독기가 쓸 수 있는 진짜 단추를 둔다. */}
                  <button
                    type="button"
                    onClick={(e) => { e.stopPropagation(); onSelect(p.id) }}
                    aria-current={isActive ? 'page' : undefined}
                    style={{
                      flex: '1 1 auto', minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                      border: 0, background: 'transparent', padding: 0, font: 'inherit', color: 'inherit',
                      textAlign: 'left', cursor: 'pointer',
                    }}
                  >
                    {p.name}
                  </button>
                  <span style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-subtle)', flexShrink: 0 }}>{p.collection_count}</span>
                  <ProjectRowActions
                    project={p}
                    isAdmin={isAdmin}
                    onStartEdit={() => startEdit(p)}
                    onAskDelete={() => setConfirmDeleteId(p.id)}
                  />
                </>
              )}
            </div>
          )
        })}
        {!isError && data && !data.items.length && (
          <p style={{ fontSize: 'var(--text-sm)', color: 'var(--color-text-muted)', padding: 'var(--space-3)' }}>
            아직 프로젝트가 없습니다.
          </p>
        )}
      </div>
    </nav>
  )
}

function NewProjectForm({ onCreated }: { onCreated: (id: string) => void }) {
  const createProject = useCreateProject()
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim()) return
    createProject.mutate(
      { name: name.trim(), description: description.trim() || undefined },
      { onSuccess: (project) => onCreated(project.id) },
    )
  }

  return (
    <Page>
      <PageHeader
        title="새 프로젝트 만들기"
        subtitle="프로젝트를 만들면 그 안에 프로젝트만의 컬렉션·문서·검색·채팅 공간이 생기고, 초대된 멤버는 이 공간에 자동으로 접근할 수 있습니다. 특정 컬렉션만 일부 멤버를 제외하고 싶을 때는 컬렉션 화면의 공유 설정에서 개별 제한할 수 있습니다."
      />
      <PageBody>
        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)', maxWidth: 480 }}>
          <Field label="프로젝트 이름">
            {(id) => (
              <Input id={id} value={name} onChange={(e) => setName(e.target.value)} placeholder="프로젝트 이름" required />
            )}
          </Field>
          <Field label="설명">
            {(id) => (
              <Textarea
                id={id}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="설명 (선택 사항)"
                rows={3}
              />
            )}
          </Field>
          {createProject.isError && <ErrorAlert error={createProject.error} message="프로젝트를 만들지 못했습니다." />}
          <div>
            <Button
              type="submit"
              variant="primary"
              disabled={createProject.isPending || !name.trim()}
              icon={createProject.isPending ? <Loader2 size={14} aria-hidden="true" style={{ animation: 'spin 1s linear infinite' }} /> : undefined}
            >
              만들기
            </Button>
          </div>
        </form>
      </PageBody>
    </Page>
  )
}
