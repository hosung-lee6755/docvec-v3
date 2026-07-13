import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import {
  AlertTriangle, Info, Loader2, Play, Save, Trash2, UploadCloud,
} from 'lucide-react'
import {
  useCreateDraftVersion,
  usePublishVersion,
  useRunWorkflow,
  useSaveWorkflowGraph,
  useWorkflowGraph,
  useWorkflowVersions,
  type WorkflowBlock,
  type WorkflowEdge as WorkflowEdgeType,
} from '../hooks/useWorkflows'
import BlockPalette from '../components/workflow/BlockPalette'
import WorkflowCanvas from '../components/workflow/WorkflowCanvas'
import BlockPropertyPanel from '../components/workflow/BlockPropertyPanel'
import { getBlockMeta } from '../lib/workflowBlocks'

export default function WorkflowEditorPage() {
  const { id: workflowId } = useParams<{ id: string }>()
  const { data: versionsData } = useWorkflowVersions(workflowId ?? null)
  // Edit the latest DRAFT version if one exists, otherwise the latest version overall
  // (a version list with only published entries means the user must create a new
  // draft before editing — enforced by the 409 the API already returns).
  const editableVersion = versionsData?.items.find((v) => !v.published_at) ?? versionsData?.items[0]
  const versionId = editableVersion?.id ?? null

  const { data: graph } = useWorkflowGraph(workflowId ?? null, versionId)
  const saveGraph = useSaveWorkflowGraph()
  const createDraftVersion = useCreateDraftVersion()
  const publishVersion = usePublishVersion()
  const runWorkflow = useRunWorkflow()

  const [blocks, setBlocks] = useState<WorkflowBlock[]>([])
  const [edges, setEdges] = useState<WorkflowEdgeType[]>([])
  const [selectedBlockId, setSelectedBlockId] = useState<string | null>(null)
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null)
  const [validationErrors, setValidationErrors] = useState<string[]>([])

  useEffect(() => {
    setBlocks(graph?.blocks ?? [])
    setEdges(graph?.edges ?? [])
  }, [graph])

  const isReadOnly = !!editableVersion?.published_at

  const handleAddBlock = (blockType: string) => {
    if (isReadOnly) return
    const newBlock: WorkflowBlock = {
      id: `temp-${crypto.randomUUID()}`,
      block_type: blockType,
      label: null,
      position: { x: 80 + blocks.length * 40, y: 80 + blocks.length * 40 },
      config: {},
    }
    setBlocks((prev) => [...prev, newBlock])
  }

  const handleMoveBlock = (blockId: string, position: { x: number; y: number }) => {
    setBlocks((prev) => prev.map((b) => (b.id === blockId ? { ...b, position } : b)))
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
  }

  const handleDeleteBlock = (blockId: string) => {
    if (isReadOnly) return
    setBlocks((prev) => prev.filter((b) => b.id !== blockId))
    setEdges((prev) => prev.filter((e) => e.from_block_id !== blockId && e.to_block_id !== blockId))
    setSelectedBlockId((prev) => (prev === blockId ? null : prev))
  }

  const handleDeleteEdge = (edgeId: string) => {
    if (isReadOnly) return
    setEdges((prev) => prev.filter((e) => e.id !== edgeId))
    setSelectedEdgeId((prev) => (prev === edgeId ? null : prev))
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
  }

  const handleSave = async () => {
    if (!workflowId || !versionId) return
    const result = await saveGraph.mutateAsync({ workflowId, versionId, graph: { blocks, edges } })
    setValidationErrors(result.validation_errors)
  }

  const handleNewDraft = async () => {
    if (!workflowId) return
    await createDraftVersion.mutateAsync(workflowId)
  }

  const handlePublish = async () => {
    if (!workflowId || !versionId) return
    await handleSave()
    await publishVersion.mutateAsync({ workflowId, versionId })
  }

  const handleRun = async () => {
    if (!workflowId || !versionId) return
    await runWorkflow.mutateAsync({ workflowId, versionId })
  }

  const selectedBlock = blocks.find((b) => b.id === selectedBlockId) ?? null
  const selectedEdge = edges.find((e) => e.id === selectedEdgeId) ?? null
  const selectedEdgeFromBlock = selectedEdge ? blocks.find((b) => b.id === selectedEdge.from_block_id) : null
  const selectedEdgeToBlock = selectedEdge ? blocks.find((b) => b.id === selectedEdge.to_block_id) : null

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--space-3)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
          <h2 style={{ fontSize: 18, fontWeight: 700, margin: 0 }}>워크플로우 편집</h2>
          {editableVersion && (
            <span className={`krds-badge small ${isReadOnly ? 'bg-primary' : 'bg-secondary'}`}>
              v{editableVersion.version_number} · {isReadOnly ? '게시됨' : '초안'}
            </span>
          )}
        </div>
        <div style={{ display: 'flex', gap: 'var(--space-2)' }}>
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
                type="button" onClick={handleSave} disabled={saveGraph.isPending}
                className="krds-btn small secondary" style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}
              >
                {saveGraph.isPending ? <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} /> : <Save size={14} />}
                저장
              </button>
              <button
                type="button" onClick={handlePublish} disabled={publishVersion.isPending}
                className="krds-btn small secondary" style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}
              >
                {publishVersion.isPending ? <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} /> : <UploadCloud size={14} />}
                게시
              </button>
            </>
          )}
          <button
            type="button" onClick={handleRun} disabled={!isReadOnly || runWorkflow.isPending}
            className="krds-btn small primary" style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}
          >
            {runWorkflow.isPending ? <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} /> : <Play size={14} />}
            실행
          </button>
        </div>
      </div>

      {isReadOnly && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 'var(--space-2)',
          padding: 'var(--space-2) var(--space-3)', background: '#eff6ff',
          border: '1px solid #bfdbfe', color: '#1d4ed8',
          borderRadius: 'var(--radius-md)', marginBottom: 'var(--space-3)', fontSize: 13,
        }}>
          <Info size={14} style={{ flexShrink: 0 }} />
          게시된 버전은 읽기 전용입니다. 블록·연결을 추가하거나 삭제하려면 "새 버전으로 저장"을 눌러 초안을 만드세요.
        </div>
      )}

      {validationErrors.length > 0 && (
        <div style={{
          display: 'flex', flexDirection: 'column', gap: 'var(--space-1)',
          padding: 'var(--space-2) var(--space-3)', background: '#fef2f2',
          border: '1px solid #fecaca', color: '#b91c1c',
          borderRadius: 'var(--radius-md)', marginBottom: 'var(--space-3)', fontSize: 13,
        }}>
          {validationErrors.map((err) => (
            <div key={err} style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
              <AlertTriangle size={14} style={{ flexShrink: 0 }} /> {err}
            </div>
          ))}
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: '220px 1fr 280px', gap: 'var(--space-3)', flex: 1, minHeight: 500 }}>
        <div style={{ border: '1px solid var(--color-border)', borderRadius: 'var(--radius-lg)', overflow: 'auto', background: 'var(--color-surface)' }}>
          <BlockPalette onAddBlock={handleAddBlock} />
        </div>
        <div style={{ border: '1px solid var(--color-border)', borderRadius: 'var(--radius-lg)', overflow: 'hidden' }}>
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
                    style={{
                      flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'center',
                      width: 26, height: 26, borderRadius: 'var(--radius-sm)', border: 'none',
                      background: 'transparent', color: 'var(--color-text-muted)', cursor: 'pointer',
                    }}
                    onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(239,68,68,0.15)'; e.currentTarget.style.color = 'var(--color-danger)' }}
                    onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = 'var(--color-text-muted)' }}
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
      <style>{`@keyframes spin { to { transform: rotate(360deg) } }`}</style>
    </div>
  )
}
