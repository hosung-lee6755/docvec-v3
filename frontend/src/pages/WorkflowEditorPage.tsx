import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams, useBlocker } from 'react-router-dom'
import { History, Loader2, Play, Save, Trash2, UploadCloud } from 'lucide-react'
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
import { Alert, Badge, Button, ErrorAlert, IconButton, Page, PageHeader, Select, SidePanel, Toolbar } from '../components/ui'
import { describeError } from '../lib/apiError'
import '../styles/screens/pipeline.css'

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

  const { data: graph, isLoading: graphLoading, error: graphError, refetch: refetchGraph } = useWorkflowGraph(workflowId ?? null, versionId)
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
      const message = describeError(err, '워크플로우를 저장하지 못했습니다.')
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
      const message = describeError(err, '새 버전을 만들지 못했습니다.')
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
      const message = describeError(err, '버전을 삭제하지 못했습니다.')
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
        setErrorMessage('아래 검증 오류를 먼저 고쳐야 게시할 수 있습니다.')
        return
      }
      await publishVersion.mutateAsync({ workflowId, versionId })
      setIsDirty(false)
    } catch (err) {
      const message = describeError(err, '버전을 게시하지 못했습니다.')
      setErrorMessage(message)
    }
  }

  const selectedBlock = blocks.find((b) => b.id === selectedBlockId) ?? null
  const selectedEdge = edges.find((e) => e.id === selectedEdgeId) ?? null
  const selectedEdgeFromBlock = selectedEdge ? blocks.find((b) => b.id === selectedEdge.from_block_id) : null
  const selectedEdgeToBlock = selectedEdge ? blocks.find((b) => b.id === selectedEdge.to_block_id) : null
  const isGraphBusy = graphLoading || !!graphError
  const paneDimClass = isGraphBusy ? ' pipeline-editor__pane--dimmed' : ''

  const headerActions = (
    <>
      <Button
        variant="ghost"
        icon={<History size={14} aria-hidden="true" />}
        onClick={() => navigate(`${projectId ? `/projects/${projectId}` : ''}/workflows/${workflowId}/runs`)}
      >
        실행 이력
      </Button>
      {isReadOnly ? (
        <Button
          variant="primary"
          onClick={handleNewDraft}
          disabled={createDraftVersion.isPending}
          icon={createDraftVersion.isPending
            ? <Loader2 size={14} className="pipeline-spin" aria-hidden="true" />
            : <Save size={14} aria-hidden="true" />}
        >
          새 버전으로 저장
        </Button>
      ) : (
        <>
          <Button
            variant="primary"
            onClick={handleSave}
            disabled={saveGraph.isPending || isGraphBusy}
            icon={saveGraph.isPending
              ? <Loader2 size={14} className="pipeline-spin" aria-hidden="true" />
              : <Save size={14} aria-hidden="true" />}
          >
            저장
          </Button>
          <Button
            variant="secondary"
            onClick={handlePublish}
            disabled={publishVersion.isPending || isGraphBusy}
            icon={publishVersion.isPending
              ? <Loader2 size={14} className="pipeline-spin" aria-hidden="true" />
              : <UploadCloud size={14} aria-hidden="true" />}
          >
            게시
          </Button>
        </>
      )}
      <Button
        variant="secondary"
        onClick={() => setShowRunModal(true)}
        disabled={!isReadOnly}
        title={isReadOnly ? undefined : '게시된 버전만 실행할 수 있습니다'}
        icon={<Play size={14} aria-hidden="true" />}
      >
        실행
      </Button>
    </>
  )

  return (
    <Page className="pipeline-editor">
      <PageHeader
        title={workflow?.name ?? '워크플로우 편집'}
        subtitle={workflow?.description || undefined}
        actions={headerActions}
      />

      <Toolbar label="버전과 종류" className="pipeline-editor__toolbar">
        {workflow && (
          <Badge tone={workflow.kind === 'PREPROCESS' ? 'info' : 'neutral'}>
            {workflow.kind === 'PREPROCESS' ? '전처리' : '분석'}
          </Badge>
        )}
        {editableVersion && (
          <Select
            value={editableVersion.id}
            onChange={(e) => setSelectedVersionId(e.target.value)}
            controlSize="sm"
            aria-label="버전 선택"
            style={{ width: 'auto', minWidth: 130 }}
          >
            {versionsData?.items.map((v) => (
              <option key={v.id} value={v.id}>
                v{v.version_number} · {v.published_at ? '게시됨' : '초안'}
              </option>
            ))}
          </Select>
        )}
        {editableVersion && (versionsData?.items.length ?? 0) > 1 && (
          confirmDeleteVersion ? (
            <div
              ref={deleteConfirmRef}
              role="alert"
              tabIndex={-1}
              className="pipeline-confirm"
            >
              <span className="pipeline-confirm__text">
                v{editableVersion.version_number}을(를) 삭제할까요?
              </span>
              <Button
                variant="danger-solid"
                size="sm"
                onClick={handleDeleteVersion}
                disabled={deleteVersion.isPending}
                autoFocus
              >
                확인
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setConfirmDeleteVersion(false)}>
                취소
              </Button>
            </div>
          ) : (
            <IconButton
              tone="danger"
              label="이 버전 삭제"
              onClick={() => {
                setConfirmDeleteVersion(true)
                // Focus will be moved to the confirm dialog after rendering
                setTimeout(() => {
                  deleteConfirmRef.current?.focus()
                }, 0)
              }}
            >
              <Trash2 size={15} aria-hidden="true" />
            </IconButton>
          )
        )}
      </Toolbar>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)', padding: 'var(--space-3) var(--space-5) 0' }}>
        {graphError && (
          <ErrorAlert error={graphError} message="워크플로우 구성을 불러오지 못했습니다." onRetry={() => refetchGraph()} />
        )}

        {isReadOnly && (
          <Alert tone="info">
            게시된 버전은 읽기 전용입니다. 블록 위치 이동·추가·삭제·연결을 하려면 "새 버전으로 저장"을 눌러 초안을 만드세요.
          </Alert>
        )}

        {errorMessage && <Alert tone="danger">{errorMessage}</Alert>}

        {validationErrors.length > 0 && (
          <Alert tone="danger">
            <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-1)' }}>
              {validationErrors.map((err, i) => (
                <div key={i}>{err.message}</div>
              ))}
            </div>
          </Alert>
        )}

        {graphLoading && <Alert tone="info">워크플로우를 로드 중입니다...</Alert>}
      </div>

      <div className="pipeline-editor__body">
        <div className={`pipeline-editor__pane${paneDimClass}`}>
          <BlockPalette onAddBlock={handleAddBlock} workflowKind={workflow?.kind} />
        </div>
        <div className={`pipeline-editor__pane pipeline-editor__canvas${paneDimClass}`}>
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
            readOnly={isReadOnly}
          />
        </div>
        {selectedEdge ? (
          <SidePanel
            title="연결"
            label="연결 속성"
            actions={!isReadOnly && (
              <Button
                variant="danger"
                size="sm"
                isBlock
                icon={<Trash2 size={14} aria-hidden="true" />}
                onClick={() => handleDeleteEdge(selectedEdge.id)}
              >
                연결 삭제
              </Button>
            )}
          >
            <div className="pipeline-editor__edge-route">
              {selectedEdgeFromBlock ? getBlockMeta(selectedEdgeFromBlock.block_type).label : '?'}
              {' → '}
              {selectedEdgeToBlock ? getBlockMeta(selectedEdgeToBlock.block_type).label : '?'}
            </div>
          </SidePanel>
        ) : (
          <div className="pipeline-editor__pane">
            <BlockPropertyPanel
              block={selectedBlock}
              onChange={handleBlockChange}
              onDelete={isReadOnly ? undefined : handleDeleteBlock}
            />
          </div>
        )}
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
    </Page>
  )
}
