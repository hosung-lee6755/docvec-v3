import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { AlertTriangle, Loader2, Play, Save, UploadCloud } from 'lucide-react'
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
    const newEdge: WorkflowEdgeType = {
      id: `temp-${crypto.randomUUID()}`,
      from_block_id: fromBlockId,
      to_block_id: toBlockId,
      condition: null,
    }
    setEdges((prev) => [...prev, newEdge])
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
            onSelectBlock={setSelectedBlockId}
            onMoveBlock={handleMoveBlock}
            onConnect={handleConnect}
          />
        </div>
        <div style={{ border: '1px solid var(--color-border)', borderRadius: 'var(--radius-lg)', overflow: 'auto', background: 'var(--color-surface)' }}>
          <BlockPropertyPanel block={selectedBlock} onChange={handleBlockChange} />
        </div>
      </div>
      <style>{`@keyframes spin { to { transform: rotate(360deg) } }`}</style>
    </div>
  )
}
