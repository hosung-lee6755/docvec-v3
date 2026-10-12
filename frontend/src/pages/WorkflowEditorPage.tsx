import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams, useBlocker } from 'react-router-dom'
import {
  AlertTriangle, History, Info, Loader2, Play, Save, Trash2, UploadCloud,
} from 'lucide-react'
import {
  useCreateDraftVersion,
  useDeleteVersion,
  usePublishVersion,
  useSaveWorkflowGraph,
  useWorkflow,
  useWorkflowGraph,
  useWorkflowVersions,
  type GraphValidationError,
  type WorkflowBlock,
  type WorkflowEdge as WorkflowEdgeType,
} from '../hooks/useWorkflows'
import BlockPalette from '../components/workflow/BlockPalette'
import WorkflowCanvas from '../components/workflow/WorkflowCanvas'
import BlockPropertyPanel from '../components/workflow/BlockPropertyPanel'
import RunWorkflowModal from '../components/workflow/RunWorkflowModal'
import { getBlockMeta } from '../lib/workflowBlocks'

export default function WorkflowEditorPage() {
  const navigate = useNavigate()
  const { id: workflowId, projectId } = useParams<{ id: string; projectId?: string }>()
  const { data: workflow } = useWorkflow(workflowId ?? null)
  const { data: versionsData } = useWorkflowVersions(workflowId ?? null)
  // User-picked version from the header select; null = auto-pick.
  const [selectedVersionId, setSelectedVersionId] = useState<string | null>(null)
  // Auto-pick: the latest DRAFT version if one exists, otherwise the latest
  // version overall (a version list with only published entries means the user
  // must create a new draft before editing — enforced by the 409 the API
  // already returns).
  const editableVersion =
    versionsData?.items.find((v) => v.id === selectedVersionId) ??
    versionsData?.items.find((v) => !v.published_at) ??
    versionsData?.items[0]
  const versionId = editableVersion?.id ?? null

  const { data: graph, isLoading: graphLoading, error: graphError } = useWorkflowGraph(workflowId ?? null, versionId)
  const saveGraph = useSaveWorkflowGraph()
  const createDraftVersion = useCreateDraftVersion()
  const deleteVersion = useDeleteVersion()
  const publishVersion = usePublishVersion()
  const [confirmDeleteVersion, setConfirmDeleteVersion] = useState(false)
  const [showRunModal, setShowRunModal] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  const [blocks, setBlocks] = useState<WorkflowBlock[]>([])
  const [edges, setEdges] = useState<WorkflowEdgeType[]>([])
  const [isDirty, setIsDirty] = useState(false)
  const [selectedBlockId, setSelectedBlockId] = useState<string | null>(null)
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null)
  const [validationErrors, setValidationErrors] = useState<GraphValidationError[]>([])
  const deleteConfirmRef = useRef<HTMLDivElement>(null)

  // Load graph only if not dirty; never overwrite unsaved edits
  useEffect(() => {
    if (!isDirty) {
      setBlocks(graph?.blocks ?? [])
      setEdges(graph?.edges ?? [])
    }
  }, [graph, isDirty])

  // Block navigation when dirty
  useBlocker(() => {
    if (isDirty && !window.confirm('저장하지 않은 변경사항이 있습니다. 페이지를 떠나시겠습니까?')) {
      return true
    }
    return false
  })

  // beforeunload warning
  useEffect(() => {
    const handleBeforeUnload = (e: BeforeUnloadEvent) => {
      if (isDirty) {
        e.preventDefault()
        e.returnValue = ''
      }
    }
    window.addEventListener('beforeunload', handleBeforeUnload)
    return () => window.removeEventListener('beforeunload', handleBeforeUnload)
  }, [isDirty])

  // Selections and stale validation errors don't carry over across versions.
  useEffect(() => {
    setSelectedBlockId(null)
    setSelectedEdgeId(null)
    setValidationErrors([])
    setConfirmDeleteVersion(false)
  }, [versionId])

  const isReadOnly = !!editableVersion?.published_at

  const handleAddBlock = (blockType: string) => {
    if (isReadOnly) return
    setBlocks((prev) => {
      const newBlock: WorkflowBlock = {
        id: `temp-${crypto.randomUUID()}`,
        block_type: blockType,
        label: null,
        // Use current length from state to avoid stale closure
        position: { x: 80 + prev.length * 40, y: 80 + prev.length * 40 },
        config: {},
      }
      return [...prev, newBlock]
    })
    setIsDirty(true)
  }

  const handleMoveBlock = (blockId: string, position: { x: number; y: number }) => {
    if (isReadOnly) return
    setBlocks((prev) => prev.map((b) => (b.id === blockId ? { ...b, position } : b)))
    setIsDirty(true)
  }

  const handleConnect = (fromBlockId: string, toBlockId: string) => {
    if (isReadOnly) return
    const newEdge: WorkflowEdgeType = {
      id: `temp-${crypto.randomUUID()}`,
      from_block_id: fromBlockId,
      to_block_id: toBlockId,
      condition: null,
    }
    setEdges((prev) => [...prev, newEdge])
    setIsDirty(true)
  }

  const handleDeleteBlock = (blockId: string) => {
    if (isReadOnly) return
    setBlocks((prev) => prev.filter((b) => b.id !== blockId))
    setEdges((prev) => prev.filter((e) => e.from_block_id !== blockId && e.to_block_id !== blockId))
    setSelectedBlockId((prev) => (prev === blockId ? null : prev))
    setIsDirty(true)
  }

  const handleDeleteEdge = (edgeId: string) => {
    if (isReadOnly) return
    setEdges((prev) => prev.filter((e) => e.id !== edgeId))
    setSelectedEdgeId((prev) => (prev === edgeId ? null : prev))
    setIsDirty(true)
  }

  const handleSelectBlock = (blockId: string | null) => {
    setSelectedBlockId(blockId)
    if (blockId) setSelectedEdgeId(null)
  }

  const handleSelectEdge = (edgeId: string | null) => {
    setSelectedEdgeId(edgeId)
    if (edgeId) setSelectedBlockId(null)
  }

  const handleBlockChange = (blockId: string, updates: { label?: string; config?: Record<string, unknown> }) => {
    setBlocks((prev) => prev.map((b) => (b.id === blockId ? { ...b, ...updates } : b)))
    setIsDirty(true)
  }

  const handleSave = async () => {
    if (!workflowId || !versionId) return
    try {
      setErrorMessage(null)
      const result = await saveGraph.mutateAsync({ workflowId, versionId, graph: { blocks, edges } })
      setValidationErrors(result.validation_errors)
      if (result.validation_errors.length === 0) {
        setIsDirty(false)
      }
      return result
    } catch (err) {
      const message = err instanceof Error ? err.message : '저장에 실패했습니다'
      setErrorMessage(message)
      throw err
    }
  }

  const handleNewDraft = async () => {
    if (!workflowId) return
    try {
      setErrorMessage(null)
      const created = await createDraftVersion.mutateAsync(workflowId)
      setSelectedVersionId(created.id)
      setIsDirty(false)
    } catch (err) {
      const message = err instanceof Error ? err.message : '버전 생성에 실패했습니다'
      setErrorMessage(message)
    }
  }

  const handleDeleteVersion = async () => {
    if (!workflowId || !versionId) return
    try {
      setErrorMessage(null)
      await deleteVersion.mutateAsync({ workflowId, versionId })
      // Fall back to auto-pick (latest draft, else latest version).
      setSelectedVersionId(null)
      setConfirmDeleteVersion(false)
    } catch (err) {
      const message = err instanceof Error ? err.message : '버전 삭제에 실패했습니다'
      setErrorMessage(message)
    }
  }

  const handlePublish = async () => {
    if (!workflowId || !versionId) return
    try {
      setErrorMessage(null)
      const saveResult = await handleSave()
      // Do not publish if there are validation errors
      if (saveResult && saveResult.validation_errors.length > 0) {
        setErrorMessage('검증 오류가 있어 게시할 수 없습니다')
        return
      }
      await publishVersion.mutateAsync({ workflowId, versionId })
      setIsDirty(false)
    } catch (err) {
      const message = err instanceof Error ? err.message : '게시에 실패했습니다'
      setErrorMessage(message)
    }
  }


  const selectedBlock = blocks.find((b) => b.id === selectedBlockId) ?? null
  const selectedEdge = edges.find((e) => e.id === selectedEdgeId) ?? null
  const selectedEdgeFromBlock = selectedEdge ? blocks.find((b) => b.id === selectedEdge.from_block_id) : null
  const selectedEdgeToBlock = selectedEdge ? blocks.find((b) => b.id === selectedEdge.to_block_id) : null

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 'var(--space-3)' }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-1)', minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
          {workflow && (
            <span className={`krds-badge small ${workflow.kind === 'PREPROCESS' ? 'bg-primary' : 'bg-secondary'}`}>
              {workflow.kind === 'PREPROCESS' ? '전처리' : '분석'}
            </span>
          )}
          <h2 style={{ fontSize: 18, fontWeight: 700, margin: 0 }}>{workflow?.name ?? '워크플로우 편집'}</h2>
          {editableVersion && (
            <select
              value={editableVersion.id}
              onChange={(e) => setSelectedVersionId(e.target.value)}
              className="krds-form-select small"
              aria-label="버전 선택"
              style={{ width: 'auto', minWidth: 130 }}
            >
              {versionsData?.items.map((v) => (
                <option key={v.id} value={v.id}>
                  v{v.version_number} · {v.published_at ? '게시됨' : '초안'}
                </option>
              ))}
            </select>
          )}
          {editableVersion && (versionsData?.items.length ?? 0) > 1 && (
            confirmDeleteVersion ? (
              <div
                ref={deleteConfirmRef}
                role="alert"
                style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}
              >
                <span style={{ fontSize: 12, color: '#dc2626' }}>
                  v{editableVersion.version_number}을(를) 삭제할까요?
                </span>
                <button
                  type="button"
                  onClick={handleDeleteVersion}
                  disabled={deleteVersion.isPending}
                  className="krds-btn xsmall primary"
                  autoFocus
                >
                  확인
                </button>
                <button
                  type="button"
                  onClick={() => setConfirmDeleteVersion(false)}
                  className="krds-btn xsmall secondary"
                >
                  취소
                </button>
              </div>
            ) : (
              <button
                type="button"
                onClick={() => {
                  setConfirmDeleteVersion(true)
                  // Focus will be moved to the confirm dialog after rendering
                  setTimeout(() => {
                    deleteConfirmRef.current?.focus()
                  }, 0)
                }}
                title="이 버전 삭제"
                aria-label="이 버전 삭제"
                className="krds-btn text xsmall icon-btn danger"
              >
                <Trash2 size={15} />
              </button>
            )
          )}
        </div>
          {workflow?.description && (
            <p style={{ margin: 0, fontSize: 12, color: 'var(--color-text-muted)' }}>
              {workflow.description}
            </p>
          )}
        </div>
        <div style={{ display: 'flex', gap: 'var(--space-2)' }}>
          <button
            type="button"
            onClick={() => navigate(`${projectId ? `/projects/${projectId}` : ''}/workflows/${workflowId}/runs`)}
            className="krds-btn small text"
            style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}
          >
            <History size={14} />
            실행 이력
          </button>
          {isReadOnly ? (
            <button
              type="button" onClick={handleNewDraft} disabled={createDraftVersion.isPending}
              className="krds-btn small secondary" style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}
            >
              {createDraftVersion.isPending ? <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} /> : <Save size={14} />}
              새 버전으로 저장
            </button>
          ) : (
            <>
              <button
                type="button"
                onClick={handleSave}
                disabled={saveGraph.isPending || graphLoading || !!graphError}
                className="krds-btn small secondary"
                style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}
              >
                {saveGraph.isPending ? <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} /> : <Save size={14} />}
                저장
              </button>
              <button
                type="button"
                onClick={handlePublish}
                disabled={publishVersion.isPending || graphLoading || !!graphError}
                className="krds-btn small secondary"
                style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}
              >
                {publishVersion.isPending ? <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} /> : <UploadCloud size={14} />}
                게시
              </button>
            </>
          )}
          <button
            type="button"
            onClick={() => setShowRunModal(true)}
            disabled={!isReadOnly}
            title={isReadOnly ? undefined : '게시된 버전만 실행할 수 있습니다'}
            className="krds-btn small primary"
            style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}
          >
            <Play size={14} />
            실행
          </button>
        </div>
      </div>

      {graphError && (
        <div
          role="alert"
          style={{
            display: 'flex', alignItems: 'center', gap: 'var(--space-2)',
            padding: 'var(--space-2) var(--space-3)', background: '#fef2f2',
            border: '1px solid #fecaca', color: '#b91c1c',
            borderRadius: 'var(--radius-md)', marginBottom: 'var(--space-3)', fontSize: 13,
          }}
        >
          <AlertTriangle size={14} style={{ flexShrink: 0 }} />
          워크플로우를 로드할 수 없습니다. 다시 시도해주세요.
        </div>
      )}

      {isReadOnly && (
        <div
          style={{
            display: 'flex', alignItems: 'center', gap: 'var(--space-2)',
            padding: 'var(--space-2) var(--space-3)', background: '#eff6ff',
            border: '1px solid #bfdbfe', color: '#1d4ed8',
            borderRadius: 'var(--radius-md)', marginBottom: 'var(--space-3)', fontSize: 13,
          }}
        >
          <Info size={14} style={{ flexShrink: 0 }} />
          게시된 버전은 읽기 전용입니다. 블록·연결을 추가하거나 삭제하려면 "새 버전으로 저장"을 눌러 초안을 만드세요.
        </div>
      )}

      {errorMessage && (
        <div
          role="alert"
          style={{
            display: 'flex', alignItems: 'center', gap: 'var(--space-2)',
            padding: 'var(--space-2) var(--space-3)', background: '#fef2f2',
            border: '1px solid #fecaca', color: '#b91c1c',
            borderRadius: 'var(--radius-md)', marginBottom: 'var(--space-3)', fontSize: 13,
          }}
        >
          <AlertTriangle size={14} style={{ flexShrink: 0 }} />
          {errorMessage}
        </div>
      )}

      {validationErrors.length > 0 && (
        <div
          role="alert"
          style={{
            display: 'flex', flexDirection: 'column', gap: 'var(--space-1)',
            padding: 'var(--space-2) var(--space-3)', background: '#fef2f2',
            border: '1px solid #fecaca', color: '#b91c1c',
            borderRadius: 'var(--radius-md)', marginBottom: 'var(--space-3)', fontSize: 13,
          }}
        >
          {validationErrors.map((err, i) => (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
              <AlertTriangle size={14} style={{ flexShrink: 0 }} /> {err.message}
            </div>
          ))}
        </div>
      )}

      {graphLoading && (
        <div
          style={{
            display: 'flex', alignItems: 'center', gap: 'var(--space-2)',
            padding: 'var(--space-2) var(--space-3)', background: '#f3f4f6',
            border: '1px solid #d1d5db', color: '#374151',
            borderRadius: 'var(--radius-md)', marginBottom: 'var(--space-3)', fontSize: 13,
          }}
        >
          <Loader2 size={14} style={{ flexShrink: 0, animation: 'spin 1s linear infinite' }} />
          워크플로우를 로드 중입니다...
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: '220px 1fr 280px', gap: 'var(--space-3)', flex: 1, minHeight: 500 }}>
        <div
          style={{
            border: '1px solid var(--color-border)',
            borderRadius: 'var(--radius-lg)',
            overflow: 'auto',
            background: 'var(--color-surface)',
            opacity: graphLoading || !!graphError ? 0.5 : 1,
            pointerEvents: graphLoading || !!graphError ? 'none' : 'auto',
          }}
        >
          <BlockPalette onAddBlock={handleAddBlock} workflowKind={workflow?.kind} />
        </div>
        <div
          style={{
            border: '1px solid var(--color-border)',
            borderRadius: 'var(--radius-lg)',
            overflow: 'hidden',
            opacity: graphLoading || !!graphError ? 0.5 : 1,
            pointerEvents: graphLoading || !!graphError ? 'none' : 'auto',
          }}
        >
          <WorkflowCanvas
            blocks={blocks}
            edges={edges}
            selectedBlockId={selectedBlockId}
            onSelectBlock={handleSelectBlock}
            selectedEdgeId={selectedEdgeId}
            onSelectEdge={handleSelectEdge}
            onMoveBlock={handleMoveBlock}
            onConnect={handleConnect}
            onDeleteBlock={handleDeleteBlock}
            onDeleteEdge={handleDeleteEdge}
            invalidBlockIds={validationErrors.map((e) => e.block_id).filter((id): id is string => !!id)}
          />
        </div>
        <div style={{ border: '1px solid var(--color-border)', borderRadius: 'var(--radius-lg)', overflow: 'auto', background: 'var(--color-surface)' }}>
          {selectedEdge ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)', padding: 'var(--space-3)' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
                <div style={{ minWidth: 0, flex: '1 1 auto' }}>
                  <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--color-text)' }}>연결</div>
                  <div style={{ fontSize: 12, color: 'var(--color-text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {selectedEdgeFromBlock ? getBlockMeta(selectedEdgeFromBlock.block_type).label : '?'}
                    {' → '}
                    {selectedEdgeToBlock ? getBlockMeta(selectedEdgeToBlock.block_type).label : '?'}
                  </div>
                </div>
                {!isReadOnly && (
                  <button
                    type="button"
                    onClick={() => handleDeleteEdge(selectedEdge.id)}
                    title="연결 삭제"
                    aria-label="연결 삭제"
                    className="krds-btn text xsmall icon-btn danger"
                    style={{ flexShrink: 0 }}
                  >
                    <Trash2 size={14} />
                  </button>
                )}
              </div>
            </div>
          ) : (
            <BlockPropertyPanel
              block={selectedBlock}
              onChange={handleBlockChange}
              onDelete={isReadOnly ? undefined : handleDeleteBlock}
            />
          )}
        </div>
      </div>
      {showRunModal && workflowId && versionId && (
        <RunWorkflowModal
          workflowId={workflowId}
          versionId={versionId}
          blocks={blocks}
          projectId={projectId}
          workflowKind={workflow?.kind}
          onClose={() => setShowRunModal(false)}
        />
      )}
      <style>{`@keyframes spin { to { transform: rotate(360deg) } }`}</style>
    </div>
  )
}
