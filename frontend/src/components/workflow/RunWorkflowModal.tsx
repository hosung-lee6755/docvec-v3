import { useState } from 'react'
import { CheckCircle2, Download, Loader2, Play, X, XCircle } from 'lucide-react'
import { useCollections } from '../../hooks/useCollections'
import { useDocuments } from '../../hooks/useDocuments'
import { apiClient } from '../../lib/apiClient'
import {
  useRunWorkflow,
  useWorkflowRun,
  useWorkflowRuns,
  type WorkflowBlock,
} from '../../hooks/useWorkflows'
import { getBlockMeta } from '../../lib/workflowBlocks'

const RUN_STATUS_BADGE: Record<string, { label: string; className: string }> = {
  QUEUED: { label: '대기 중', className: 'bg-secondary' },
  RUNNING: { label: '실행 중', className: 'bg-information' },
  COMPLETED: { label: '완료', className: 'bg-primary' },
  FAILED: { label: '실패', className: 'bg-danger' },
  CANCELLED: { label: '취소됨', className: 'bg-tertiary' },
  PENDING: { label: '대기', className: 'bg-secondary' },
}

interface RunWorkflowModalProps {
  workflowId: string
  versionId: string
  blocks: WorkflowBlock[]
  projectId?: string
  onClose: () => void
}

export default function RunWorkflowModal({
  workflowId, versionId, blocks, projectId, onClose,
}: RunWorkflowModalProps) {
  const { data: documentsData } = useDocuments({ projectId, limit: 100 })
  const { data: collectionsData } = useCollections(projectId)
  const runWorkflow = useRunWorkflow()
  const { data: runsData } = useWorkflowRuns(workflowId)
  const [targetType, setTargetType] = useState<'document' | 'collection'>('document')
  const [documentId, setDocumentId] = useState('')
  const [collectionId, setCollectionId] = useState('')
  const [startedCount, setStartedCount] = useState<number | null>(null)
  const [activeRunId, setActiveRunId] = useState<string | null>(null)
  const { data: runDetail } = useWorkflowRun(activeRunId)

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
      versionId,
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

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 50,
    }}>
      <section className="krds-modal fade shown in" role="dialog">
        <div className="modal-dialog modal-md">
          <div className="modal-content">
            <div className="modal-header">
              <h2 className="modal-title">워크플로우 실행</h2>
            </div>
            <div className="modal-conts">
              <div className="conts-area" style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
                <div className="form-group">
                  <div className="form-tit">
                    <label htmlFor="run_target">실행 대상</label>
                  </div>
                  <div className="form-conts" style={{ display: 'flex', gap: 'var(--space-2)' }}>
                    <select
                      className="krds-form-select"
                      style={{ flex: '0 0 110px', width: 110 }}
                      value={targetType}
                      onChange={(e) => setTargetType(e.target.value as 'document' | 'collection')}
                      aria-label="대상 유형"
                    >
                      <option value="document">문서</option>
                      <option value="collection">컬렉션</option>
                    </select>
                    {targetType === 'document' ? (
                      <select
                        id="run_target"
                        className="krds-form-select"
                        style={{ flex: '1 1 auto' }}
                        value={documentId}
                        onChange={(e) => setDocumentId(e.target.value)}
                      >
                        <option value="">문서를 선택하세요</option>
                        {documentsData?.items.map((d) => (
                          <option key={d.id} value={d.id}>{d.original_filename}</option>
                        ))}
                      </select>
                    ) : (
                      <select
                        id="run_target"
                        className="krds-form-select"
                        style={{ flex: '1 1 auto' }}
                        value={collectionId}
                        onChange={(e) => setCollectionId(e.target.value)}
                      >
                        <option value="">컬렉션을 선택하세요</option>
                        {collectionsData?.items.map((c) => (
                          <option key={c.id} value={c.id}>{c.name}</option>
                        ))}
                      </select>
                    )}
                    <button
                      type="button"
                      onClick={handleStart}
                      disabled={!canStart || runWorkflow.isPending}
                      className="krds-btn medium primary"
                      style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-1)', flexShrink: 0 }}
                    >
                      {runWorkflow.isPending
                        ? <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} />
                        : <Play size={14} />}
                      실행
                    </button>
                  </div>
                  {targetType === 'collection' && (
                    <p className="form-hint">컬렉션 내 파싱 완료된 문서마다 개별 실행이 만들어집니다 (최대 50건).</p>
                  )}
                  {startedCount !== null && startedCount > 1 && (
                    <p className="form-hint" style={{ color: '#1d4ed8' }}>
                      {startedCount}건의 실행이 시작되었습니다. 아래 실행 이력에서 각각 확인하세요.
                    </p>
                  )}
                </div>

                {activeRun && (
                  <div style={{
                    border: '1px solid #e2e8f0', borderRadius: 'var(--radius-md)',
                    padding: 'var(--space-3)', display: 'flex', flexDirection: 'column', gap: 'var(--space-2)',
                  }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
                      <strong style={{ fontSize: 13 }}>진행 상황</strong>
                      <span className={`krds-badge small ${RUN_STATUS_BADGE[activeRun.status]?.className ?? 'bg-secondary'}`}>
                        {RUN_STATUS_BADGE[activeRun.status]?.label ?? activeRun.status}
                      </span>
                      {(activeRun.status === 'QUEUED' || activeRun.status === 'RUNNING') && (
                        <Loader2 size={13} style={{ animation: 'spin 1s linear infinite', color: '#2563eb' }} />
                      )}
                      {activeRun.status === 'COMPLETED' && (
                        <button
                          type="button"
                          onClick={() => handleExport(activeRun.id)}
                          className="krds-btn xsmall text"
                          style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 4 }}
                        >
                          <Download size={13} /> 결과 내보내기 (JSON)
                        </button>
                      )}
                    </div>
                    {activeRun.error_message && (
                      <div style={{
                        background: '#fef2f2', border: '1px solid #fecaca', color: '#b91c1c',
                        borderRadius: 'var(--radius-sm)', padding: 'var(--space-2)', fontSize: 12,
                      }}>
                        {activeRun.error_message}
                      </div>
                    )}
                    {steps.map((step) => {
                      const output = step.output
                        ? Object.fromEntries(Object.entries(step.output).filter(([k]) => k !== 'text'))
                        : null
                      return (
                        <div key={step.id} style={{
                          display: 'flex', flexDirection: 'column', gap: 4,
                          padding: 'var(--space-2)', background: '#f8fafc', borderRadius: 'var(--radius-sm)',
                        }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', fontSize: 13 }}>
                            {step.status === 'COMPLETED' && <CheckCircle2 size={14} style={{ color: '#16a34a' }} />}
                            {step.status === 'FAILED' && <XCircle size={14} style={{ color: '#dc2626' }} />}
                            {(step.status === 'PENDING' || step.status === 'RUNNING') && (
                              <Loader2 size={14} style={{ animation: 'spin 1s linear infinite', color: '#2563eb' }} />
                            )}
                            <strong>{blockName(step.block_instance_id)}</strong>
                            <span style={{ fontSize: 11, color: '#94a3b8' }}>
                              {RUN_STATUS_BADGE[step.status]?.label ?? step.status}
                            </span>
                          </div>
                          {step.error_message && (
                            <div style={{ fontSize: 12, color: '#b91c1c' }}>{step.error_message}</div>
                          )}
                          {output && Object.keys(output).length > 0 && (
                            <pre style={{
                              margin: 0, fontSize: 11, whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                              color: '#475569', maxHeight: 140, overflow: 'auto',
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
                    <strong style={{ fontSize: 13 }}>실행 이력</strong>
                    <ul style={{ margin: 'var(--space-2) 0 0', padding: 0, listStyle: 'none', display: 'flex', flexDirection: 'column', gap: 4 }}>
                      {runsData.items.slice(0, 10).map((r) => (
                        <li key={r.id}>
                          <button
                            type="button"
                            onClick={() => setActiveRunId(r.id)}
                            style={{
                              width: '100%', display: 'flex', alignItems: 'center', gap: 'var(--space-2)',
                              padding: 'var(--space-1) var(--space-2)', fontSize: 12, textAlign: 'left',
                              border: '1px solid #e2e8f0', borderRadius: 'var(--radius-sm)',
                              background: r.id === activeRunId ? '#eff6ff' : '#fff', cursor: 'pointer',
                            }}
                          >
                            <span className={`krds-badge xsmall ${RUN_STATUS_BADGE[r.status]?.className ?? 'bg-secondary'}`}>
                              {RUN_STATUS_BADGE[r.status]?.label ?? r.status}
                            </span>
                            <span style={{ color: '#475569' }}>
                              {new Date(r.created_at).toLocaleString('ko-KR')}
                            </span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                <div className="modal-btn btn-wrap">
                  <button type="button" className="krds-btn medium secondary" onClick={onClose}>
                    닫기
                  </button>
                </div>
              </div>
            </div>
            <button type="button" className="krds-btn medium icon btn-close close-modal" onClick={onClose}>
              <span className="sr-only">닫기</span>
              <X size={20} />
            </button>
          </div>
        </div>
        <div className="modal-back"></div>
      </section>
      <style>{`@keyframes spin { to { transform: rotate(360deg) } }`}</style>
    </div>
  )
}
