import { useEffect, useState } from 'react'
import { CheckCircle2, Download, Loader2, Play, XCircle } from 'lucide-react'
import { useCollections } from '../../hooks/useCollections'
import { useDocuments } from '../../hooks/useDocuments'
import { apiClient } from '../../lib/apiClient'
import {
  useRunWorkflow,
  useWorkflowRun,
  useWorkflowRuns,
  useWorkflowVersions,
  type WorkflowBlock,
} from '../../hooks/useWorkflows'
import { getBlockMeta } from '../../lib/workflowBlocks'
import { Alert, Badge, Button, Field, Modal, Select } from '../ui'
import type { BadgeTone } from '../ui/classes'
import '../../styles/screens/pipeline.css'

const RUN_STATUS_BADGE: Record<string, { label: string; tone: BadgeTone }> = {
  QUEUED: { label: '대기 중', tone: 'neutral' },
  RUNNING: { label: '실행 중', tone: 'info' },
  COMPLETED: { label: '완료', tone: 'success' },
  FAILED: { label: '실패', tone: 'danger' },
  CANCELLED: { label: '취소됨', tone: 'neutral' },
  PENDING: { label: '대기', tone: 'neutral' },
}

interface RunWorkflowModalProps {
  workflowId: string
  versionId: string
  blocks: WorkflowBlock[]
  projectId?: string
  workflowKind?: 'PREPROCESS' | 'ANALYSIS'
  onClose: () => void
}

function StepIcon({ status }: { status: string }) {
  if (status === 'COMPLETED') return <CheckCircle2 size={14} className="wf-step__icon--success" aria-hidden="true" />
  if (status === 'FAILED') return <XCircle size={14} className="wf-step__icon--danger" aria-hidden="true" />
  if (status === 'PENDING' || status === 'RUNNING') {
    return <Loader2 size={14} className="wf-step__icon--primary pipeline-spin" aria-hidden="true" />
  }
  return null
}

export default function RunWorkflowModal({
  workflowId, versionId, blocks, projectId, workflowKind, onClose,
}: RunWorkflowModalProps) {
  const { data: documentsData } = useDocuments({ projectId, limit: 100 })
  const { data: collectionsData } = useCollections(projectId)
  const { data: versionsData } = useWorkflowVersions(workflowId)
  const runWorkflow = useRunWorkflow()
  const { data: runsData } = useWorkflowRuns(workflowId)
  const [targetType, setTargetType] = useState<'document' | 'collection'>('document')
  const [documentId, setDocumentId] = useState('')
  const [collectionId, setCollectionId] = useState('')
  const [runVersionId, setRunVersionId] = useState(versionId)
  const [startedCount, setStartedCount] = useState<number | null>(null)
  const [activeRunId, setActiveRunId] = useState<string | null>(null)
  const { data: runDetail } = useWorkflowRun(activeRunId)

  useEffect(() => {
    setRunVersionId(versionId)
  }, [versionId])

  const blockName = (blockInstanceId: string) => {
    const block = blocks.find((b) => b.id === blockInstanceId)
    if (!block) return blockInstanceId.slice(0, 8)
    return block.label || getBlockMeta(block.block_type).label
  }

  const canStart = targetType === 'document' ? !!documentId : !!collectionId

  const handleStart = async () => {
    if (!canStart) return
    const result = await runWorkflow.mutateAsync({
      workflowId,
      versionId: runVersionId,
      documentId: targetType === 'document' ? documentId : undefined,
      collectionId: targetType === 'collection' ? collectionId : undefined,
    })
    setStartedCount(result.count)
    setActiveRunId(result.items[0]?.id ?? null)
  }

  const handleExport = async (runId: string) => {
    const { data } = await apiClient.get(`/workflows/runs/${runId}/export`, { responseType: 'blob' })
    const url = URL.createObjectURL(data)
    const a = document.createElement('a')
    a.href = url
    a.download = `workflow-run-${runId}.json`
    a.click()
    URL.revokeObjectURL(url)
  }

  const activeRun = runDetail?.run
  const steps = runDetail?.steps ?? []
  const isRunActive = activeRun?.status === 'QUEUED' || activeRun?.status === 'RUNNING'

  return (
    <Modal
      isOpen
      title="워크플로우 실행"
      onClose={onClose}
      size="lg"
      footer={<Button variant="secondary" onClick={onClose}>닫기</Button>}
    >
      <div className="pipeline-modal-stack">
        {workflowKind === 'PREPROCESS' && (
          <Alert tone="warning">이 워크플로우를 실행하면 대상 문서의 기존 RAG 데이터를 대체합니다.</Alert>
        )}

        <Field label="실행 버전">
          {(id) => (
            <Select id={id} value={runVersionId} onChange={(e) => setRunVersionId(e.target.value)}>
              {versionsData?.items.map((v) => (
                <option key={v.id} value={v.id}>
                  v{v.version_number}{v.published_at ? ' (발행됨)' : ' (초안)'}{v.id === versionId ? ' — 현재 편집 중' : ''}
                </option>
              ))}
            </Select>
          )}
        </Field>

        <Field label="실행 대상">
          {(id) => (
            <div style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'center' }}>
              <Select
                aria-label="대상 유형"
                value={targetType}
                onChange={(e) => setTargetType(e.target.value as 'document' | 'collection')}
                style={{ flex: '0 0 110px', width: 110 }}
              >
                <option value="document">문서</option>
                <option value="collection">컬렉션</option>
              </Select>
              {targetType === 'document' ? (
                <Select
                  id={id}
                  style={{ flex: '1 1 auto', minWidth: 0 }}
                  value={documentId}
                  onChange={(e) => setDocumentId(e.target.value)}
                >
                  <option value="">문서를 선택하세요</option>
                  {documentsData?.items.map((d) => (
                    <option key={d.id} value={d.id}>{d.original_filename}</option>
                  ))}
                </Select>
              ) : (
                <Select
                  id={id}
                  style={{ flex: '1 1 auto', minWidth: 0 }}
                  value={collectionId}
                  onChange={(e) => setCollectionId(e.target.value)}
                >
                  <option value="">컬렉션을 선택하세요</option>
                  {collectionsData?.items.map((c) => (
                    <option key={c.id} value={c.id}>{c.name}</option>
                  ))}
                </Select>
              )}
              <Button
                variant="primary"
                onClick={handleStart}
                disabled={!canStart || runWorkflow.isPending}
                icon={runWorkflow.isPending
                  ? <Loader2 size={14} className="pipeline-spin" aria-hidden="true" />
                  : <Play size={14} aria-hidden="true" />}
                style={{ flexShrink: 0 }}
              >
                실행
              </Button>
            </div>
          )}
        </Field>
        {targetType === 'collection' && (
          <p className="wf-muted">컬렉션 내 파싱 완료된 문서마다 개별 실행이 만들어집니다 (최대 50건).</p>
        )}
        {startedCount !== null && startedCount > 1 && (
          <p className="wf-muted" style={{ color: 'var(--color-primary)' }}>
            {startedCount}건의 실행이 시작되었습니다. 아래 실행 이력에서 각각 확인하세요.
          </p>
        )}

        {activeRun && (
          <div className="wf-steps" style={{
            border: '1px solid var(--color-border)', borderRadius: 'var(--radius-md)', padding: 'var(--space-3)',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
              <strong style={{ fontSize: 'var(--text-sm)' }}>진행 상황</strong>
              <Badge tone={RUN_STATUS_BADGE[activeRun.status]?.tone ?? 'neutral'} hasDot>
                {RUN_STATUS_BADGE[activeRun.status]?.label ?? activeRun.status}
              </Badge>
              {isRunActive && (
                <Loader2 size={13} className="wf-step__icon--primary pipeline-spin" aria-hidden="true" />
              )}
              {activeRun.status === 'COMPLETED' && (
                <span style={{ marginLeft: 'auto' }}>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => handleExport(activeRun.id)}
                    icon={<Download size={13} aria-hidden="true" />}
                  >
                    결과 내보내기 (JSON)
                  </Button>
                </span>
              )}
            </div>
            {activeRun.error_message && <Alert tone="danger">{activeRun.error_message}</Alert>}
            {steps.map((step) => {
              const output = step.output
                ? Object.fromEntries(Object.entries(step.output).filter(([k]) => k !== 'text'))
                : null
              return (
                <div key={step.id} className="wf-step">
                  <div className="wf-step__head">
                    <StepIcon status={step.status} />
                    <span className="wf-step__name">{blockName(step.block_instance_id)}</span>
                    <span className="wf-step__status">
                      {RUN_STATUS_BADGE[step.status]?.label ?? step.status}
                    </span>
                  </div>
                  {step.error_message && (
                    <div style={{ fontSize: 'var(--text-xs)', color: 'var(--color-danger)' }}>{step.error_message}</div>
                  )}
                  {output && Object.keys(output).length > 0 && (
                    <pre style={{
                      margin: 0, fontSize: 'var(--text-xs)', whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                      color: 'var(--color-text-secondary)', maxHeight: 140, overflow: 'auto', fontFamily: 'var(--font-mono)',
                    }}>
                      {JSON.stringify(output, null, 2)}
                    </pre>
                  )}
                </div>
              )
            })}
          </div>
        )}

        {!!runsData?.items.length && (
          <div>
            <strong style={{ fontSize: 'var(--text-sm)' }}>실행 이력</strong>
            <ul style={{ margin: 'var(--space-2) 0 0', padding: 0, listStyle: 'none', display: 'flex', flexDirection: 'column', gap: 4 }}>
              {runsData.items.slice(0, 10).map((r) => (
                <li key={r.id}>
                  <button
                    type="button"
                    onClick={() => setActiveRunId(r.id)}
                    aria-pressed={r.id === activeRunId}
                    className="pipeline-menu__item"
                    style={{
                      border: '1px solid var(--color-border)',
                      background: r.id === activeRunId ? 'var(--color-primary-subtle)' : 'var(--color-surface)',
                      gap: 'var(--space-2)',
                    }}
                  >
                    <Badge tone={RUN_STATUS_BADGE[r.status]?.tone ?? 'neutral'} hasDot>
                      {RUN_STATUS_BADGE[r.status]?.label ?? r.status}
                    </Badge>
                    <span style={{ color: 'var(--color-text-secondary)' }}>
                      {new Date(r.created_at).toLocaleString('ko-KR')}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </Modal>
  )
}
