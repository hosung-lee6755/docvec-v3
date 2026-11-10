import { useEffect, useMemo, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { FolderOpen, FolderPlus, Trash2, X, Loader2, Pencil, Users, UserPlus, UserMinus, BarChart3, Layers } from 'lucide-react'
import {
  useCollectionMembers,
  useCollections,
  useCreateCollection,
  useDeleteCollection,
  useEmbeddingModels,
  useInviteMember,
  useRemoveMember,
  useReprocessCollection,
  useUpdateCollection,
  type Collection,
} from '../hooks/useCollections'
import { useProjects } from '../hooks/useProjects'
import { useAuthStore } from '../store/authStore'
import { useWorkflowGraph, useWorkflowVersions, useWorkflows, type WorkflowGraph } from '../hooks/useWorkflows'
import { getBlockMeta } from '../lib/workflowBlocks'
import { apiClient } from '../lib/apiClient'
import GoldenEvalModal from '../components/GoldenEvalModal'
import VectorStatsModal from '../components/VectorStatsModal'
import { SECURITY_LEVELS, SECURITY_LEVEL_LABELS } from '../hooks/useAccess'
import type { SecurityLevel } from '../hooks/useDocumentMetadata'

// 그래프의 블록 체인을 진입 블록에서부터 첫 번째 나가는 에지를 따라가며 한 줄로
// 요약 — 컬렉션 설정 화면의 "문서 처리" 섹션이 보여줄 미리보기용 단순화(분기가
// 있는 그래프는 첫 갈래만 보여준다).
function buildBlockChainPreview(graph: WorkflowGraph): string {
  const hasIncoming = new Set(graph.edges.map((e) => e.to_block_id))
  const outgoing = new Map(graph.edges.map((e) => [e.from_block_id, e.to_block_id]))
  const entry = graph.blocks.find((b) => !hasIncoming.has(b.id))
  if (!entry) return graph.blocks.map((b) => getBlockMeta(b.block_type).label).join(' → ')

  const chain: string[] = []
  let current: typeof entry | undefined = entry
  const visited = new Set<string>()
  while (current && !visited.has(current.id)) {
    chain.push(getBlockMeta(current.block_type).label)
    visited.add(current.id)
    const nextId = outgoing.get(current.id)
    current = nextId ? graph.blocks.find((b) => b.id === nextId) : undefined
  }
  return chain.join(' → ')
}

export default function CollectionsPage() {
  const location = useLocation()
  const navigate = useNavigate()
  const { projectId: routeProjectId } = useParams<{ projectId?: string }>()
  const { data, isLoading, isError } = useCollections(routeProjectId)
  const { data: projectsData } = useProjects()
  const { data: embeddingModels } = useEmbeddingModels()
  const createCollection = useCreateCollection()
  const deleteCollection = useDeleteCollection()
  const updateCollection = useUpdateCollection()
  const reprocessCollection = useReprocessCollection()
  const [reprocessResult, setReprocessResult] = useState<string | null>(null)
  const [reprocessConfirming, setReprocessConfirming] = useState(false)
  const [isExporting, setIsExporting] = useState(false)

  const handleExport = async (id: string) => {
    setIsExporting(true)
    try {
      const { data } = await apiClient.get(`/collections/${id}/export`, { responseType: 'blob' })
      const url = URL.createObjectURL(data)
      const a = document.createElement('a')
      a.href = url
      a.download = `collection-${id}-export.json`
      a.click()
      URL.revokeObjectURL(url)
    } finally {
      setIsExporting(false)
    }
  }
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [newName, setNewName] = useState('')
  const [newDescription, setNewDescription] = useState('')
  const [newProjectId, setNewProjectId] = useState('')
  // '' = 표준 전처리(시스템 기본값) / 지정 안 함.
  const [newWorkflowId, setNewWorkflowId] = useState('')
  const [newAnalysisWorkflowId, setNewAnalysisWorkflowId] = useState('')
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null)
  const [editId, setEditId] = useState<string | null>(null)
  const [editName, setEditName] = useState('')
  const [editDescription, setEditDescription] = useState('')
  const [editSecurityLevel, setEditSecurityLevel] = useState<'' | SecurityLevel>('')
  const [editProjectId, setEditProjectId] = useState('')
  const [shareId, setShareId] = useState<string | null>(null)
  const [shareName, setShareName] = useState('')
  const [shareProjectId, setShareProjectId] = useState<string | null>(null)
  const [shareRestrict, setShareRestrict] = useState(false)
  const [inviteEmail, setInviteEmail] = useState('')
  const [inviteRole, setInviteRole] = useState<'viewer' | 'editor'>('viewer')
  const [inviteError, setInviteError] = useState<string | null>(null)
  const [inviteSuccess, setInviteSuccess] = useState<string | null>(null)
  const [confirmRemoveUserId, setConfirmRemoveUserId] = useState<string | null>(null)
  const { data: memberData, isLoading: membersLoading } = useCollectionMembers(shareId)
  const inviteMember = useInviteMember()
  const removeMember = useRemoveMember()
  const isAdmin = useAuthStore((s) => s.user?.role === 'admin')

  // Only projects where this user has editor+ access can receive a new/reassigned
  // collection (create_collection/update_collection enforce this server-side too).
  const editableProjects = (projectsData?.items ?? []).filter(
    (p) => p.is_owner || p.role === 'editor'
  )

  useEffect(() => {
    const state = location.state as { openCreate?: boolean; projectId?: string } | null
    if (state?.openCreate) {
      setShowCreateModal(true)
      if (state.projectId) setNewProjectId(state.projectId)
      navigate(location.pathname, { replace: true, state: null })
    }
  }, [location, navigate])

  useEffect(() => {
    if (routeProjectId) setNewProjectId(routeProjectId)
  }, [routeProjectId])
  const [editDocCount, setEditDocCount] = useState(0)
  // '' = 표준 전처리(시스템 기본값) — Collection.default_workflow_id가 null일 때의 의미.
  const [editWorkflowId, setEditWorkflowId] = useState('')
  const [editVersionMode, setEditVersionMode] = useState<'latest' | 'pinned'>('latest')
  const [editVersionNumber, setEditVersionNumber] = useState<number | null>(null)
  // '' = 자동 분석 없음 — Collection.default_analysis_workflow_id가 null일 때의 의미.
  const [editAnalysisWorkflowId, setEditAnalysisWorkflowId] = useState('')
  const [editAnalysisVersionMode, setEditAnalysisVersionMode] = useState<'latest' | 'pinned'>('latest')
  const [editAnalysisVersionNumber, setEditAnalysisVersionNumber] = useState<number | null>(null)
  const [goldenEvalCollection, setGoldenEvalCollection] = useState<Collection | null>(null)
  const [vectorStatsCollection, setVectorStatsCollection] = useState<Collection | null>(null)
  const editingCollection = data?.items.find((c) => c.id === editId)

  // 시스템 표준 워크플로우는 project_id가 없어 GET /workflows?project_id=에 절대
  // 나오지 않는다 — 개인(프로젝트 없는) 컬렉션은 커스텀 전처리 워크플로우를 가질
  // 수 없으므로 "표준 전처리(시스템 기본값)" 옵션 하나만 고를 수 있다.
  const { data: projectPreprocessWorkflows } = useWorkflows(editingCollection?.project_id ?? null, 'PREPROCESS')
  const { data: projectAnalysisWorkflows } = useWorkflows(editingCollection?.project_id ?? null, 'ANALYSIS')
  const { data: newProjectPreprocessWorkflows } = useWorkflows(newProjectId || null, 'PREPROCESS')
  const { data: newProjectAnalysisWorkflows } = useWorkflows(newProjectId || null, 'ANALYSIS')
  const { data: editWorkflowVersions } = useWorkflowVersions(editWorkflowId || null)
  const publishedVersions = useMemo(
    () => (editWorkflowVersions?.items ?? []).filter((v) => v.published_at).sort((a, b) => b.version_number - a.version_number),
    [editWorkflowVersions],
  )
  const previewVersionId = useMemo(() => {
    if (editVersionMode === 'pinned' && editVersionNumber != null) {
      return publishedVersions.find((v) => v.version_number === editVersionNumber)?.id ?? null
    }
    return publishedVersions[0]?.id ?? null
  }, [editVersionMode, editVersionNumber, publishedVersions])
  const { data: previewGraph } = useWorkflowGraph(editWorkflowId || null, previewVersionId)
  const { data: editAnalysisWorkflowVersions } = useWorkflowVersions(editAnalysisWorkflowId || null)
  const analysisPublishedVersions = useMemo(
    () => (editAnalysisWorkflowVersions?.items ?? []).filter((v) => v.published_at).sort((a, b) => b.version_number - a.version_number),
    [editAnalysisWorkflowVersions],
  )
  const [createNameError, setCreateNameError] = useState(false)
  const [editNameError, setEditNameError] = useState(false)

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!newName.trim()) {
      setCreateNameError(true)
      return
    }
    setCreateNameError(false)
    await createCollection.mutateAsync({
      name: newName.trim(),
      description: newDescription.trim() || undefined,
      project_id: newProjectId || undefined,
      default_workflow_id: newWorkflowId || undefined,
      default_analysis_workflow_id: newAnalysisWorkflowId || undefined,
    })
    setNewName('')
    setNewDescription('')
    setNewProjectId('')
    setNewWorkflowId('')
    setNewAnalysisWorkflowId('')
    setShowCreateModal(false)
  }

  const handleDelete = async (id: string) => {
    await deleteCollection.mutateAsync(id)
    setConfirmDeleteId(null)
  }

  const handleReprocess = async (id: string) => {
    setReprocessConfirming(false)
    setReprocessResult(null)
    const result = await reprocessCollection.mutateAsync(id)
    setReprocessResult(`${result.queued}건 재처리 시작됨${result.skipped ? ` (${result.skipped}건 건너뜀)` : ''}`)
  }

  const openShareModal = (col: Collection) => {
    setShareId(col.id)
    setShareName(col.name)
    setShareProjectId(col.project_id)
    setShareRestrict(col.restrict_to_members)
    setInviteEmail('')
    setInviteRole('viewer')
    setInviteError(null)
    setInviteSuccess(null)
    setConfirmRemoveUserId(null)
  }

  const closeShareModal = () => {
    setShareId(null)
    setShareName('')
    setShareProjectId(null)
    setShareRestrict(false)
    setInviteEmail('')
    setInviteError(null)
    setInviteSuccess(null)
    setConfirmRemoveUserId(null)
  }

  const handleToggleRestrict = async () => {
    if (!shareId) return
    const next = !shareRestrict
    await updateCollection.mutateAsync({ id: shareId, name: shareName, restrict_to_members: next })
    setShareRestrict(next)
  }

  const handleInvite = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!shareId || !inviteEmail.trim()) return
    setInviteError(null)
    setInviteSuccess(null)
    try {
      const invitedEmail = inviteEmail.trim()
      const invitedRoleLabel = inviteRole === 'editor' ? '편집자' : '조회자'
      await inviteMember.mutateAsync({ collectionId: shareId, email: invitedEmail, role: inviteRole })
      setInviteEmail('')
      setInviteRole('viewer')
      setInviteSuccess(`${invitedEmail}님을 ${invitedRoleLabel}로 초대했습니다.`)
    } catch {
      setInviteError('초대에 실패했습니다. 가입된 사용자의 이메일인지 확인하세요.')
    }
  }

  const handleRemoveMember = async (userId: string) => {
    if (!shareId) return
    await removeMember.mutateAsync({ collectionId: shareId, userId })
    setConfirmRemoveUserId(null)
  }

  const handleEdit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!editId || !editName.trim()) {
      setEditNameError(true)
      return
    }
    setEditNameError(false)
    try {
      await updateCollection.mutateAsync({
        id: editId,
        name: editName.trim(),
        description: editDescription.trim() || undefined,
        project_id: editProjectId || undefined,
        default_security_level: editSecurityLevel || null,
        ...(editWorkflowId
          ? { default_workflow_id: editWorkflowId, default_workflow_version: editVersionMode === 'pinned' ? editVersionNumber : null }
          : { clear_default_workflow: true }),
        ...(editAnalysisWorkflowId
          ? {
            default_analysis_workflow_id: editAnalysisWorkflowId,
            default_analysis_workflow_version: editAnalysisVersionMode === 'pinned' ? editAnalysisVersionNumber : null,
          }
          : { clear_default_analysis_workflow: true }),
      })
      setEditId(null)
      setEditName('')
      setEditDescription('')
    } catch {
      // modal stays open; error shown via updateCollection.isError
    }
  }

  return (
    <div>
      <style>{`
        @keyframes spin { to { transform: rotate(360deg) } }
      `}</style>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--space-6)' }}>
        <h1 style={{ fontSize: 24, fontWeight: 700 }}>컬렉션</h1>
        <button
          type="button"
          onClick={() => setShowCreateModal(true)}
          className="krds-btn small tertiary"
          style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-1)' }}
        >
          <FolderPlus size={14} /> 새 컬렉션
        </button>
      </div>

      {isLoading && (
        <div style={{ display: 'flex', justifyContent: 'center', padding: 'var(--space-8)' }}>
          <Loader2 size={24} style={{ animation: 'spin 1s linear infinite', color: 'var(--color-text-muted)' }} />
        </div>
      )}

      {isError && (
        <div style={{
          background: '#fef2f2', border: '1px solid #dc2626',
          borderRadius: 'var(--radius-md)', padding: 'var(--space-4)',
          color: '#dc2626', marginBottom: 'var(--space-4)',
        }}>
          컬렉션 목록을 불러오지 못했습니다.
        </div>
      )}

      {!isLoading && !isError && data?.items.length === 0 && (
        <div style={{ textAlign: 'center', padding: 'var(--space-8)', color: 'var(--color-text-muted)' }}>
          <FolderOpen size={48} style={{ margin: '0 auto var(--space-4)', display: 'block', opacity: 0.4 }} />
          <p>컬렉션이 없습니다. 새 컬렉션을 만들어 보세요.</p>
        </div>
      )}

      {!isLoading && !isError && (data?.items.length ?? 0) > 0 && (
        <div className="krds-table-wrap">
          <table className="tbl col data">
            <caption>컬렉션 목록</caption>
            <colgroup>
              <col style={{ width: '15%' }} />
              <col style={{ width: '20%' }} />
              <col style={{ width: '15%' }} />
              <col style={{ width: '15%' }} />
              <col style={{ width: '20%' }} />
              <col />
            </colgroup>
            <thead>
              <tr>
                <th scope="col">이름</th>
                <th scope="col">설명</th>
                <th scope="col">임베딩 모델</th>
                <th scope="col">청킹</th>
                <th scope="col">생성일</th>
                <th scope="col">작업</th>
              </tr>
            </thead>
            <tbody>
              {data?.items.map((col) => (
                <tr key={col.id}>
                  <td style={{ fontWeight: 500 }}>
                    <span
                      onClick={() => navigate(
                        `${routeProjectId ? `/projects/${routeProjectId}` : ''}/documents?collection=${col.id}`
                      )}
                      title="이 컬렉션의 문서 보기"
                      style={{ cursor: 'pointer', color: 'var(--color-accent)' }}
                    >
                      {col.name}
                    </span>
                    {col.project_name && (
                      <span
                        className="krds-badge xsmall bg-secondary"
                        style={{ marginLeft: 'var(--space-2)' }}
                        title={`${col.project_name} 프로젝트에 속함`}
                      >
                        {col.project_name}
                      </span>
                    )}
                    {!col.is_owner && (
                      <span
                        className="krds-badge xsmall bg-information"
                        style={{ marginLeft: 'var(--space-2)' }}
                        title={`${col.role === 'editor' ? '편집자' : '조회자'} 권한으로 공유받음`}
                      >
                        공유받음
                      </span>
                    )}
                  </td>
                  <td style={{ color: 'var(--color-text-muted)' }}>{col.description ?? '—'}</td>
                  <td>
                    {embeddingModels?.items.find((m) => m.key === col.embedding_model)?.label ?? col.embedding_model}
                    {(col.reembed_status === 'PENDING' || col.reembed_status === 'RUNNING') && (
                      <div style={{ fontSize: 11, color: '#2563eb', display: 'flex', alignItems: 'center', gap: 4, marginTop: 2 }}>
                        <Loader2 size={11} style={{ animation: 'spin 1s linear infinite' }} />
                        재임베딩 중 {col.reembed_progress}
                      </div>
                    )}
                    {col.reembed_status === 'FAILED' && (
                      <div style={{ fontSize: 11, color: '#dc2626', marginTop: 2 }} title={col.reembed_progress ?? undefined}>
                        재임베딩 일부 실패
                      </div>
                    )}
                  </td>
                  <td style={{ color: 'var(--color-text-muted)', whiteSpace: 'nowrap' }}>
                    {col.chunk_max_tokens}자 / 겹침 {col.chunk_overlap_tokens}자
                  </td>
                  <td style={{ color: 'var(--color-text-muted)', whiteSpace: 'nowrap' }}>
                    {new Date(col.created_at).toLocaleDateString('ko-KR')}
                  </td>
                  <td>
                    {confirmDeleteId === col.id ? (
                      <div style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'center' }}>
                        <span style={{ fontSize: 12, color: '#dc2626' }}>삭제하시겠습니까?</span>
                        <button
                          onClick={() => handleDelete(col.id)}
                          disabled={deleteCollection.isPending}
                          className="krds-btn xsmall primary"
                        >확인</button>
                        <button
                          onClick={() => setConfirmDeleteId(null)}
                          className="krds-btn xsmall secondary"
                        >취소</button>
                      </div>
                    ) : (
                      <div style={{ display: 'flex', gap: 'var(--space-1)' }}>
                        {col.is_owner && (
                          <button
                            type="button"
                            onClick={() => openShareModal(col)}
                            className="krds-btn text xsmall icon-btn accent"
                            title="공유"
                            aria-label="공유"
                          >
                            <Users size={17} />
                          </button>
                        )}
                        <button
                          type="button"
                          onClick={() => {
                            setEditId(col.id)
                            setEditName(col.name)
                            setEditDescription(col.description ?? '')
                            setEditSecurityLevel(col.default_security_level ?? '')
                            setEditProjectId(col.project_id ?? '')
                            setEditDocCount(col.document_count)
                            setEditWorkflowId(col.default_workflow_id ?? '')
                            setEditVersionMode(col.default_workflow_version != null ? 'pinned' : 'latest')
                            setEditVersionNumber(col.default_workflow_version)
                            setEditAnalysisWorkflowId(col.default_analysis_workflow_id ?? '')
                            setEditAnalysisVersionMode(col.default_analysis_workflow_version != null ? 'pinned' : 'latest')
                            setEditAnalysisVersionNumber(col.default_analysis_workflow_version)
                            setReprocessResult(null)
                            setReprocessConfirming(false)
                          }}
                          className="krds-btn text xsmall icon-btn accent"
                          title={col.is_owner || col.role === 'editor' ? '수정' : '편집 권한이 있어야 수정할 수 있습니다'}
                          aria-label="수정"
                          disabled={!(col.is_owner || col.role === 'editor')}
                        >
                          <Pencil size={17} />
                        </button>
                        <button
                          type="button"
                          onClick={() => setGoldenEvalCollection(col)}
                          className="krds-btn text xsmall icon-btn accent"
                          title="골든 쿼리 평가"
                          aria-label="골든 쿼리 평가"
                        >
                          <BarChart3 size={17} />
                        </button>
                        <button
                          type="button"
                          onClick={() => setVectorStatsCollection(col)}
                          className="krds-btn text xsmall icon-btn accent"
                          title="벡터 DB 현황"
                          aria-label="벡터 DB 현황"
                        >
                          <Layers size={17} />
                        </button>
                        {(col.is_owner || isAdmin) && (
                          <button
                            type="button"
                            onClick={() => setConfirmDeleteId(col.id)}
                            className="krds-btn text xsmall icon-btn danger"
                            title="삭제"
                            aria-label="삭제"
                          >
                            <Trash2 size={17} />
                          </button>
                        )}
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showCreateModal && (
        <div style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 50,
        }}>
          <section className="krds-modal fade shown in" role="dialog">
            <div className="modal-dialog modal-sm">
              <div className="modal-content">
                <div className="modal-header">
                  <h2 className="modal-title">새 컬렉션 만들기</h2>
                </div>
                <div className="modal-conts">
                  <div className="conts-area">
                    <form onSubmit={handleCreate} style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
                      <div className="form-group">
                        <div className="form-tit">
                          <label htmlFor="create_name">
                            이름 <span style={{ color: '#dc2626' }}>*</span>
                          </label>
                        </div>
                        <div className="form-conts">
                          <input
                            id="create_name"
                            type="text"
                            className={`krds-input ${createNameError ? 'is-error' : ''}`}
                            value={newName}
                            onChange={(e) => {
                              setNewName(e.target.value)
                              setCreateNameError(false)
                            }}
                            placeholder="컬렉션 이름"
                            required
                          />
                        </div>
                        {createNameError && <p className="form-hint-invalid">이름을 입력하세요.</p>}
                      </div>

                      <div className="form-group">
                        <div className="form-tit">
                          <label htmlFor="create_desc">설명</label>
                        </div>
                        <div className="form-conts">
                          <div className="textarea-wrap">
                            <textarea
                              id="create_desc"
                              className="krds-input"
                              value={newDescription}
                              onChange={(e) => setNewDescription(e.target.value)}
                              placeholder="선택 사항"
                              rows={3}
                            />
                          </div>
                        </div>
                      </div>

                      <div className="form-group">
                        <div className="form-tit">
                          <label htmlFor="edit_security_level">기본 보안등급</label>
                        </div>
                        <div className="form-conts">
                          <select
                            id="edit_security_level"
                            className="krds-form-select"
                            value={editSecurityLevel}
                            onChange={(e) => setEditSecurityLevel(e.target.value as '' | SecurityLevel)}
                          >
                            <option value="">지정 안 함 (공개)</option>
                            {SECURITY_LEVELS.map((level) => (
                              <option key={level} value={level}>{SECURITY_LEVEL_LABELS[level]}</option>
                            ))}
                          </select>
                          <p className="form-hint" style={{ fontSize: 12, color: 'var(--color-text-muted)', marginTop: 4 }}>
                            문서에 보안등급을 따로 지정하지 않으면 이 등급이 적용됩니다. 사용자의 열람등급보다 높은 문서는 검색·채팅·목록에 나오지 않습니다.
                          </p>
                        </div>
                      </div>

                      {!routeProjectId && (
                        <div className="form-group">
                          <div className="form-tit">
                            <label htmlFor="create_project">프로젝트</label>
                          </div>
                          <div className="form-conts">
                            <select
                              id="create_project"
                              className="krds-form-select"
                              value={newProjectId}
                              onChange={(e) => setNewProjectId(e.target.value)}
                            >
                              <option value="">개인 컬렉션 (프로젝트 없음)</option>
                              {editableProjects.map((p) => (
                                <option key={p.id} value={p.id}>{p.name}</option>
                              ))}
                            </select>
                          </div>
                          <p className="form-hint">
                            프로젝트를 지정하면 해당 프로젝트의 모든 멤버가 이 컬렉션에 자동으로 접근할 수 있습니다.
                          </p>
                        </div>
                      )}

                      <div className="form-group">
                        <div className="form-tit">
                          <label htmlFor="create_workflow">기본 전처리 워크플로우</label>
                        </div>
                        <div className="form-conts">
                          <select
                            id="create_workflow"
                            className="krds-form-select"
                            value={newWorkflowId}
                            onChange={(e) => setNewWorkflowId(e.target.value)}
                          >
                            <option value="">표준 전처리 (시스템 기본값)</option>
                            {(newProjectPreprocessWorkflows?.items ?? []).filter((wf) => !wf.is_system_default).map((wf) => (
                              <option key={wf.id} value={wf.id}>{wf.name}</option>
                            ))}
                          </select>
                        </div>
                        <p className="form-hint">
                          업로드되는 문서의 임베딩 모델·청킹 방식은 이 워크플로우의 문서분할·RAG저장 블록 설정을 따릅니다.
                        </p>
                      </div>

                      <div className="form-group">
                        <div className="form-tit">
                          <label htmlFor="create_analysis_workflow">기본 분석 워크플로우</label>
                        </div>
                        <div className="form-conts">
                          <select
                            id="create_analysis_workflow"
                            className="krds-form-select"
                            value={newAnalysisWorkflowId}
                            onChange={(e) => setNewAnalysisWorkflowId(e.target.value)}
                          >
                            <option value="">자동 분석 안 함</option>
                            {(newProjectAnalysisWorkflows?.items ?? []).map((wf) => (
                              <option key={wf.id} value={wf.id}>{wf.name}</option>
                            ))}
                          </select>
                        </div>
                        <p className="form-hint">
                          지정하면 전처리가 끝난 직후 이 워크플로우가 문서마다 자동으로 실행됩니다(요약·키워드 등이 문서에 자동 반영).
                        </p>
                      </div>

                      {createCollection.isError && (
                        <div style={{
                          background: '#fef2f2', border: '1px solid #dc2626',
                          borderRadius: 'var(--radius-md)', padding: 'var(--space-3)',
                          color: '#dc2626', fontSize: 13,
                        }}>
                          컬렉션 생성에 실패했습니다.
                        </div>
                      )}

                      <div className="modal-btn btn-wrap">
                        <button
                          type="button"
                          className="krds-btn medium secondary"
                          onClick={() => setShowCreateModal(false)}
                        >
                          취소
                        </button>
                        <button
                          type="submit"
                          className="krds-btn medium primary"
                          disabled={createCollection.isPending || !newName.trim()}
                          style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', justifyContent: 'center' }}
                        >
                          {createCollection.isPending && <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} />}
                          만들기
                        </button>
                      </div>
                    </form>
                  </div>
                </div>
                <button
                  type="button"
                  className="krds-btn medium icon btn-close close-modal"
                  onClick={() => setShowCreateModal(false)}
                >
                  <span className="sr-only">닫기</span>
                  <X size={20} />
                </button>
              </div>
            </div>
            <div className="modal-back"></div>
          </section>
        </div>
      )}

      {editId && (
        <div style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 50,
        }}>
          <section className="krds-modal fade shown in" role="dialog">
            <div className="modal-dialog modal-sm">
              <div className="modal-content">
                <div className="modal-header">
                  <h2 className="modal-title">컬렉션 수정</h2>
                </div>
                <div className="modal-conts">
                  <div className="conts-area">
                    <form onSubmit={handleEdit} style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
                      <div className="form-group">
                        <div className="form-tit">
                          <label htmlFor="edit_name">
                            이름 <span style={{ color: '#dc2626' }}>*</span>
                          </label>
                        </div>
                        <div className="form-conts">
                          <input
                            id="edit_name"
                            type="text"
                            className={`krds-input ${editNameError ? 'is-error' : ''}`}
                            value={editName}
                            onChange={(e) => {
                              setEditName(e.target.value)
                              setEditNameError(false)
                            }}
                            placeholder="컬렉션 이름"
                            required
                          />
                        </div>
                        {editNameError && <p className="form-hint-invalid">이름을 입력하세요.</p>}
                      </div>

                      <div className="form-group">
                        <div className="form-tit">
                          <label htmlFor="edit_desc">설명</label>
                        </div>
                        <div className="form-conts">
                          <div className="textarea-wrap">
                            <textarea
                              id="edit_desc"
                              className="krds-input"
                              value={editDescription}
                              onChange={(e) => setEditDescription(e.target.value)}
                              placeholder="선택 사항"
                              rows={3}
                            />
                          </div>
                        </div>
                      </div>

                      {!routeProjectId && (
                        <div className="form-group">
                          <div className="form-tit">
                            <label htmlFor="edit_project">프로젝트</label>
                          </div>
                          <div className="form-conts">
                            <select
                              id="edit_project"
                              className="krds-form-select"
                              value={editProjectId}
                              onChange={(e) => setEditProjectId(e.target.value)}
                            >
                              <option value="">개인 컬렉션 (프로젝트 없음)</option>
                              {editableProjects.map((p) => (
                                <option key={p.id} value={p.id}>{p.name}</option>
                              ))}
                            </select>
                          </div>
                          <p className="form-hint">
                            프로젝트를 지정하면 해당 프로젝트의 모든 멤버가 이 컬렉션에 자동으로 접근할 수 있습니다.
                            이미 프로젝트에 속한 컬렉션을 개인 컬렉션으로 되돌리는 것은 이 화면에서 지원하지 않습니다.
                          </p>
                        </div>
                      )}

                      <div className="form-group">
                        <div className="form-tit">
                          <label htmlFor="edit_workflow">문서 처리 — 기본 워크플로우</label>
                        </div>
                        <div className="form-conts">
                          <select
                            id="edit_workflow"
                            className="krds-form-select"
                            value={editWorkflowId}
                            onChange={(e) => {
                              setEditWorkflowId(e.target.value)
                              setEditVersionMode('latest')
                              setEditVersionNumber(null)
                            }}
                          >
                            <option value="">표준 전처리 (시스템 기본값)</option>
                            {(projectPreprocessWorkflows?.items ?? []).filter((wf) => !wf.is_system_default).map((wf) => (
                              <option key={wf.id} value={wf.id}>{wf.name}</option>
                            ))}
                          </select>
                        </div>
                        <p className="form-hint">
                          이 컬렉션에 업로드되는 문서에 기본 적용될 전처리 워크플로우입니다.
                          {!editingCollection?.project_id && ' 개인 컬렉션은 프로젝트에 속한 커스텀 워크플로우를 가질 수 없어 시스템 기본값만 선택할 수 있습니다.'}
                        </p>
                      </div>

                      {editWorkflowId && (
                        <div className="form-group">
                          <div className="form-tit">
                            <label>버전</label>
                          </div>
                          <div className="form-conts" style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                            <div className="krds-form-check" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                              <input
                                type="radio"
                                id="edit_version_mode_latest"
                                name="edit_version_mode"
                                checked={editVersionMode === 'latest'}
                                onChange={() => { setEditVersionMode('latest'); setEditVersionNumber(null) }}
                              />
                              <label htmlFor="edit_version_mode_latest" style={{ fontSize: 13, fontWeight: 400 }}>
                                항상 최신 발행 버전
                              </label>
                            </div>
                            <div className="krds-form-check" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                              <input
                                type="radio"
                                id="edit_version_mode_pinned"
                                name="edit_version_mode"
                                checked={editVersionMode === 'pinned'}
                                onChange={() => setEditVersionMode('pinned')}
                              />
                              <label htmlFor="edit_version_mode_pinned" style={{ fontSize: 13, fontWeight: 400 }}>
                                버전 고정
                              </label>
                              {editVersionMode === 'pinned' && (
                                <select
                                  className="krds-form-select"
                                  style={{ marginLeft: 6, width: 'auto' }}
                                  value={editVersionNumber ?? ''}
                                  onChange={(e) => setEditVersionNumber(e.target.value ? Number(e.target.value) : null)}
                                >
                                  <option value="">선택</option>
                                  {publishedVersions.map((v) => (
                                    <option key={v.id} value={v.version_number}>v{v.version_number}</option>
                                  ))}
                                </select>
                              )}
                            </div>
                          </div>
                        </div>
                      )}

                      {editWorkflowId && previewGraph && previewGraph.blocks.length > 0 && (
                        <p className="form-hint" style={{
                          background: '#f8fafc', border: '1px solid var(--color-border, #e2e8f0)',
                          borderRadius: 'var(--radius-md)', padding: 'var(--space-2) var(--space-3)',
                        }}>
                          {buildBlockChainPreview(previewGraph)}
                        </p>
                      )}

                      <div className="form-group">
                        <div className="form-tit">
                          <label htmlFor="edit_analysis_workflow">기본 분석 워크플로우</label>
                        </div>
                        <div className="form-conts">
                          <select
                            id="edit_analysis_workflow"
                            className="krds-form-select"
                            value={editAnalysisWorkflowId}
                            onChange={(e) => {
                              setEditAnalysisWorkflowId(e.target.value)
                              setEditAnalysisVersionMode('latest')
                              setEditAnalysisVersionNumber(null)
                            }}
                          >
                            <option value="">자동 분석 안 함</option>
                            {(projectAnalysisWorkflows?.items ?? []).map((wf) => (
                              <option key={wf.id} value={wf.id}>{wf.name}</option>
                            ))}
                          </select>
                        </div>
                        <p className="form-hint">
                          지정하면 전처리가 끝난 직후 이 워크플로우가 문서마다 자동으로 실행됩니다(요약·키워드 등이 문서에 자동 반영).
                        </p>
                      </div>

                      {editAnalysisWorkflowId && (
                        <div className="form-group">
                          <div className="form-tit">
                            <label>버전</label>
                          </div>
                          <div className="form-conts" style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                            <div className="krds-form-check" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                              <input
                                type="radio"
                                id="edit_analysis_version_mode_latest"
                                name="edit_analysis_version_mode"
                                checked={editAnalysisVersionMode === 'latest'}
                                onChange={() => { setEditAnalysisVersionMode('latest'); setEditAnalysisVersionNumber(null) }}
                              />
                              <label htmlFor="edit_analysis_version_mode_latest" style={{ fontSize: 13, fontWeight: 400 }}>
                                항상 최신 발행 버전
                              </label>
                            </div>
                            <div className="krds-form-check" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                              <input
                                type="radio"
                                id="edit_analysis_version_mode_pinned"
                                name="edit_analysis_version_mode"
                                checked={editAnalysisVersionMode === 'pinned'}
                                onChange={() => setEditAnalysisVersionMode('pinned')}
                              />
                              <label htmlFor="edit_analysis_version_mode_pinned" style={{ fontSize: 13, fontWeight: 400 }}>
                                버전 고정
                              </label>
                              {editAnalysisVersionMode === 'pinned' && (
                                <select
                                  className="krds-form-select"
                                  style={{ marginLeft: 6, width: 'auto' }}
                                  value={editAnalysisVersionNumber ?? ''}
                                  onChange={(e) => setEditAnalysisVersionNumber(e.target.value ? Number(e.target.value) : null)}
                                >
                                  <option value="">선택</option>
                                  {analysisPublishedVersions.map((v) => (
                                    <option key={v.id} value={v.version_number}>v{v.version_number}</option>
                                  ))}
                                </select>
                              )}
                            </div>
                          </div>
                        </div>
                      )}

                      {updateCollection.isError && (
                        <div style={{
                          background: '#fef2f2', border: '1px solid #dc2626',
                          borderRadius: 'var(--radius-md)', padding: 'var(--space-3)',
                          color: '#dc2626', fontSize: 13,
                        }}>
                          컬렉션 수정에 실패했습니다.
                        </div>
                      )}

                      {reprocessResult && (
                        <div style={{
                          background: '#eff6ff', border: '1px solid #bfdbfe',
                          borderRadius: 'var(--radius-md)', padding: 'var(--space-3)',
                          color: '#1d4ed8', fontSize: 13,
                        }}>
                          {reprocessResult}
                        </div>
                      )}

                      {reprocessConfirming ? (
                        <div style={{
                          display: 'flex', flexDirection: 'column', gap: 'var(--space-2)',
                          background: '#fef2f2', border: '1px solid #dc2626',
                          borderRadius: 'var(--radius-md)', padding: 'var(--space-3)',
                          marginBottom: 'var(--space-3)',
                        }}>
                          <span style={{ fontSize: 13, color: '#dc2626' }}>
                            문서 {editDocCount}건을 현재 설정으로 다시 처리합니다. 예상 소요 시간은 약 {Math.max(1, Math.ceil(editDocCount * 0.5))}분입니다. 계속할까요?
                          </span>
                          <div style={{ display: 'flex', gap: 'var(--space-2)', justifyContent: 'flex-end' }}>
                            <button
                              type="button"
                              onClick={() => setReprocessConfirming(false)}
                              className="krds-btn xsmall secondary"
                            >취소</button>
                            <button
                              type="button"
                              onClick={() => editId && handleReprocess(editId)}
                              disabled={reprocessCollection.isPending}
                              className="krds-btn xsmall primary"
                            >확인</button>
                          </div>
                        </div>
                      ) : (
                        <button
                          type="button"
                          className="krds-btn medium tertiary"
                          disabled={reprocessCollection.isPending || editDocCount === 0}
                          onClick={() => setReprocessConfirming(true)}
                          style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 'var(--space-2)', width: '100%', marginBottom: 'var(--space-3)' }}
                        >
                          {reprocessCollection.isPending && <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} />}
                          이 설정으로 다시 처리
                        </button>
                      )}

                      <button
                        type="button"
                        className="krds-btn medium tertiary"
                        disabled={isExporting}
                        onClick={() => editId && handleExport(editId)}
                        style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 'var(--space-2)', width: '100%', marginBottom: 'var(--space-3)' }}
                      >
                        {isExporting && <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} />}
                        RAG 데이터 내보내기 (JSON)
                      </button>

                      <div className="modal-btn btn-wrap">
                        <button
                          type="button"
                          className="krds-btn medium secondary"
                          onClick={() => setEditId(null)}
                        >
                          취소
                        </button>
                        <button
                          type="submit"
                          className="krds-btn medium primary"
                          disabled={updateCollection.isPending || !editName.trim()}
                          style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', justifyContent: 'center' }}
                        >
                          {updateCollection.isPending && <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} />}
                          저장
                        </button>
                      </div>
                    </form>
                  </div>
                </div>
                <button
                  type="button"
                  className="krds-btn medium icon btn-close close-modal"
                  onClick={() => setEditId(null)}
                >
                  <span className="sr-only">닫기</span>
                  <X size={20} />
                </button>
              </div>
            </div>
            <div className="modal-back"></div>
          </section>
        </div>
      )}

      {shareId && (
        <div style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 50,
        }}>
          <section className="krds-modal fade shown in" role="dialog">
            <div className="modal-dialog modal-md">
              <div className="modal-content">
                <div className="modal-header">
                  <h2 className="modal-title">컬렉션 공유</h2>
                  <p style={{ margin: 'var(--space-1) 0 0', fontSize: 13, color: 'var(--color-text-muted)' }}>
                    {shareName}
                  </p>
                </div>
                <div className="modal-conts">
                  <div className="conts-area" style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-5)' }}>
                    {shareProjectId && (
                      <div className="krds-form-check" style={{
                        display: 'flex', alignItems: 'flex-start', gap: 'var(--space-3)',
                        padding: 'var(--space-3)', background: '#f8fafc',
                        border: '1px solid #e2e8f0', borderRadius: 'var(--radius-md)',
                      }}>
                        <input
                          type="checkbox"
                          className="chk"
                          id="restrict_to_members"
                          checked={shareRestrict}
                          onChange={handleToggleRestrict}
                          disabled={updateCollection.isPending}
                          style={{ marginTop: 3, flexShrink: 0 }}
                        />
                        <label htmlFor="restrict_to_members" style={{ fontSize: 13, lineHeight: 1.5, cursor: 'pointer' }}>
                          <strong>이 컬렉션만 별도로 공유 범위 제한</strong>
                          <br />
                          <span style={{ color: 'var(--color-text-muted)' }}>
                            켜면 프로젝트 멤버 전체 자동 접근이 꺼지고, 아래에서 초대한 멤버만 접근할 수 있습니다.
                            (프로젝트 전체 인원 중 일부를 제외하고 싶을 때 사용)
                          </span>
                        </label>
                      </div>
                    )}
                    <form onSubmit={handleInvite} style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
                      <div className="form-group">
                        <div className="form-tit">
                          <label htmlFor="invite_email">이메일로 초대</label>
                        </div>
                        <div className="form-conts" style={{ display: 'flex', flexDirection: 'row', flexWrap: 'wrap', gap: 'var(--space-2)' }}>
                          <input
                            id="invite_email"
                            type="email"
                            className="krds-input"
                            style={{ flex: '1 1 auto' }}
                            value={inviteEmail}
                            onChange={(e) => setInviteEmail(e.target.value)}
                            placeholder="user@example.com"
                            required
                          />
                          <select
                            className="krds-form-select"
                            style={{ flex: '0 0 128px', width: 128 }}
                            value={inviteRole}
                            onChange={(e) => setInviteRole(e.target.value as 'viewer' | 'editor')}
                          >
                            <option value="viewer">조회자</option>
                            <option value="editor">편집자</option>
                          </select>
                          <button
                            type="submit"
                            className="krds-btn small primary"
                            disabled={inviteMember.isPending || !inviteEmail.trim()}
                            style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-1)', flex: '0 0 auto', whiteSpace: 'nowrap' }}
                          >
                            {inviteMember.isPending
                              ? <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} />
                              : <UserPlus size={14} />}
                            초대
                          </button>
                        </div>
                      </div>

                      <p style={{ margin: 0, fontSize: 12, color: 'var(--color-text-muted)', lineHeight: 1.6 }}>
                        <strong>조회자</strong>는 문서 검색·열람만 가능하고, <strong>편집자</strong>는 문서 업로드도 할 수 있습니다.
                        컬렉션 삭제·설정 변경·멤버 관리는 소유자만 할 수 있습니다.
                      </p>

                      {inviteError && (
                        <div style={{
                          background: '#fef2f2', border: '1px solid #dc2626',
                          borderRadius: 'var(--radius-md)', padding: 'var(--space-3)',
                          color: '#dc2626', fontSize: 13,
                        }}>
                          {inviteError}
                        </div>
                      )}
                      {inviteSuccess && (
                        <div style={{
                          background: '#eff6ff', border: '1px solid #bfdbfe',
                          borderRadius: 'var(--radius-md)', padding: 'var(--space-3)',
                          color: '#1d4ed8', fontSize: 13,
                        }}>
                          {inviteSuccess}
                        </div>
                      )}
                    </form>

                    <div>
                      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 'var(--space-2)' }}>
                        <h3 style={{ fontSize: 14, fontWeight: 600, margin: 0 }}>멤버</h3>
                        {!membersLoading && (
                          <span style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
                            총 {memberData?.items.length ?? 0}명
                          </span>
                        )}
                      </div>

                      {membersLoading && (
                        <div style={{ display: 'flex', justifyContent: 'center', padding: 'var(--space-4)' }}>
                          <Loader2 size={18} style={{ animation: 'spin 1s linear infinite', color: 'var(--color-text-muted)' }} />
                        </div>
                      )}

                      {!membersLoading && (memberData?.items.length ?? 0) <= 1 && (
                        <p style={{
                          margin: 0, padding: 'var(--space-4)', textAlign: 'center',
                          fontSize: 13, color: 'var(--color-text-muted)',
                          background: '#f8fafc', borderRadius: 'var(--radius-md)',
                        }}>
                          아직 초대한 멤버가 없습니다. 위에서 이메일로 초대해 보세요.
                        </p>
                      )}

                      {!membersLoading && (memberData?.items.length ?? 0) > 1 && (
                        <ul style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)', margin: 0, padding: 0, listStyle: 'none' }}>
                          {memberData?.items.map((m) => (
                            <li
                              key={m.user_id}
                              style={{
                                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                                padding: 'var(--space-2) var(--space-3)', border: '1px solid #e2e8f0',
                                borderRadius: 'var(--radius-md)', background: '#fff',
                              }}
                            >
                              <div style={{ minWidth: 0 }}>
                                <div style={{ fontSize: 14, fontWeight: 500 }}>{m.username || m.email}</div>
                                <div style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>{m.email}</div>
                              </div>
                              <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', flexShrink: 0 }}>
                                {confirmRemoveUserId === m.user_id ? (
                                  <>
                                    <span style={{ fontSize: 12, color: '#dc2626', whiteSpace: 'nowrap' }}>제거할까요?</span>
                                    <button
                                      type="button"
                                      onClick={() => handleRemoveMember(m.user_id)}
                                      disabled={removeMember.isPending}
                                      className="krds-btn xsmall primary"
                                    >확인</button>
                                    <button
                                      type="button"
                                      onClick={() => setConfirmRemoveUserId(null)}
                                      className="krds-btn xsmall secondary"
                                    >취소</button>
                                  </>
                                ) : (
                                  <>
                                    <span className="krds-badge xsmall bg-information">
                                      {m.role === 'owner' ? '소유자' : m.role === 'editor' ? '편집자' : '조회자'}
                                    </span>
                                    {m.role !== 'owner' && (
                                      <button
                                        type="button"
                                        onClick={() => setConfirmRemoveUserId(m.user_id)}
                                        className="krds-btn text xsmall icon-btn danger"
                                        title="멤버 제거"
                                        aria-label="멤버 제거"
                                      >
                                        <UserMinus size={16} />
                                      </button>
                                    )}
                                  </>
                                )}
                              </div>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>

                    <div className="modal-btn btn-wrap">
                      <button
                        type="button"
                        className="krds-btn medium secondary"
                        onClick={closeShareModal}
                      >
                        닫기
                      </button>
                    </div>
                  </div>
                </div>
                <button
                  type="button"
                  className="krds-btn medium icon btn-close close-modal"
                  onClick={closeShareModal}
                >
                  <span className="sr-only">닫기</span>
                  <X size={20} />
                </button>
              </div>
            </div>
            <div className="modal-back"></div>
          </section>
        </div>
      )}

      {goldenEvalCollection && (
        <GoldenEvalModal
          collectionId={goldenEvalCollection.id}
          collectionName={goldenEvalCollection.name}
          onClose={() => setGoldenEvalCollection(null)}
        />
      )}

      {vectorStatsCollection && (
        <VectorStatsModal
          collectionId={vectorStatsCollection.id}
          collectionName={vectorStatsCollection.name}
          onClose={() => setVectorStatsCollection(null)}
        />
      )}
    </div>
  )
}
