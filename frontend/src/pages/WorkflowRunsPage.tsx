import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  ArrowLeft, Download, FileText, FolderOpen, Trash2,
} from 'lucide-react'
import {
  useDeleteRun,
  useWorkflow,
  useWorkflowGraph,
  useWorkflowRun,
  useWorkflowRuns,
} from '../hooks/useWorkflows'
import { apiClient } from '../lib/apiClient'
import { getBlockMeta } from '../lib/workflowBlocks'
import StepTimeline from '../components/workflow/StepTimeline'

const RUN_STATUS_BADGE: Record<string, { label: string; className: string }> = {
  QUEUED: { label: '대기 중', className: 'bg-secondary' },
  RUNNING: { label: '실행 중', className: 'bg-information' },
  COMPLETED: { label: '완료', className: 'bg-primary' },
  FAILED: { label: '실패', className: 'bg-danger' },
  CANCELLED: { label: '취소됨', className: 'bg-tertiary' },
  PENDING: { label: '대기', className: 'bg-secondary' },
}

const CHANGE_FIELD_LABELS: Record<string, string> = {
  summary: '요약',
  suggested_tags: '추천 태그',
}

function formatDuration(startedAt: string | null, completedAt: string | null): string {
  if (!startedAt || !completedAt) return '-'
  const ms = new Date(completedAt).getTime() - new Date(startedAt).getTime()
  if (ms < 0) return '-'
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}초`
}

interface RunChange {
  field: string
  before: unknown
  after: unknown
}

function ChangeView({ change }: { change: RunChange }) {
  const label = CHANGE_FIELD_LABELS[change.field] ?? change.field
  if (Array.isArray(change.after)) {
    const before = new Set((Array.isArray(change.before) ? change.before : []).map((t) => String(t).toLowerCase()))
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        <strong style={{ fontSize: 12 }}>{label}</strong>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
          {change.after.map((tag) => {
            const isNew = !before.has(String(tag).toLowerCase())
            return (
              <span
                key={String(tag)}
                className={`krds-badge xsmall ${isNew ? 'bg-primary' : 'bg-secondary'}`}
                title={isNew ? '이번 실행에서 추가됨' : '기존에 있던 항목'}
              >
                {isNew ? '+ ' : ''}{String(tag)}
              </span>
            )
          })}
        </div>
      </div>
    )
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <strong style={{ fontSize: 12 }}>{label}</strong>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 'var(--space-2)' }}>
        <div style={{
          padding: 'var(--space-2)', background: '#fef2f2', border: '1px solid #fecaca',
          borderRadius: 'var(--radius-sm)', fontSize: 12, whiteSpace: 'pre-wrap', wordBreak: 'break-word',
          maxHeight: 180, overflow: 'auto',
        }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: '#b91c1c', marginBottom: 4 }}>변경 전</div>
          {change.before ? String(change.before) : <span style={{ color: '#94a3b8' }}>(없음)</span>}
        </div>
        <div style={{
          padding: 'var(--space-2)', background: '#f0fdf4', border: '1px solid #bbf7d0',
          borderRadius: 'var(--radius-sm)', fontSize: 12, whiteSpace: 'pre-wrap', wordBreak: 'break-word',
          maxHeight: 180, overflow: 'auto',
        }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: '#15803d', marginBottom: 4 }}>변경 후</div>
          {change.after ? String(change.after) : <span style={{ color: '#94a3b8' }}>(없음)</span>}
        </div>
      </div>
    </div>
  )
}

export default function WorkflowRunsPage() {
  const navigate = useNavigate()
  const { id: workflowId, projectId } = useParams<{ id: string; projectId?: string }>()
  const { data: workflow } = useWorkflow(workflowId ?? null)
  const { data: runsData } = useWorkflowRuns(workflowId ?? null)
  const deleteRun = useDeleteRun()
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null)
  const { data: runDetail } = useWorkflowRun(selectedRunId)

  const selectedRun = runsData?.items.find((r) => r.id === selectedRunId) ?? null
  // Block names come from the graph of the version the run executed.
  const { data: graph } = useWorkflowGraph(workflowId ?? null, selectedRun?.version_id ?? null)

  const basePath = projectId ? `/projects/${projectId}` : ''

  const blockName = (blockInstanceId: string) => {
    const block = graph?.blocks.find((b) => b.id === blockInstanceId)
    if (!block) return blockInstanceId.slice(0, 8)
    return block.label || getBlockMeta(block.block_type).label
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

  const steps = runDetail?.steps ?? []
  const changes: RunChange[] = steps.flatMap((s) =>
    Array.isArray((s.output as Record<string, unknown> | null)?.changes)
      ? ((s.output as Record<string, unknown>).changes as RunChange[])
      : [],
  )

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', marginBottom: 'var(--space-4)' }}>
        <button
          type="button"
          onClick={() => navigate(`${basePath}/workflows/${workflowId}/edit`)}
          className="krds-btn small text"
          style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-1)' }}
        >
          <ArrowLeft size={14} /> 에디터로
        </button>
        <h2 style={{ fontSize: 18, fontWeight: 700, margin: 0 }}>
          실행 이력{workflow ? ` — ${workflow.name}` : ''}
        </h2>
      </div>

      {!runsData?.items.length && (
        <div style={{
          padding: 'var(--space-8)', textAlign: 'center', color: '#94a3b8',
          border: '1px dashed #e2e8f0', borderRadius: 'var(--radius-lg)',
        }}>
          아직 실행 이력이 없습니다. 에디터에서 게시된 버전을 실행해 보세요.
        </div>
      )}

      {!!runsData?.items.length && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 'var(--space-4)', alignItems: 'start' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ textAlign: 'left', borderBottom: '1px solid #e2e8f0' }}>
                {['실행 시각', '버전', '대상', '상태', '소요 시간', ''].map((h) => (
                  <th key={h} style={{ padding: 'var(--space-2)', color: '#94a3b8', fontSize: 11, fontWeight: 700, textTransform: 'uppercase', whiteSpace: 'nowrap' }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {runsData.items.map((run) => (
                <tr
                  key={run.id}
                  onClick={() => setSelectedRunId(run.id)}
                  style={{
                    borderBottom: '1px solid #e2e8f0', cursor: 'pointer',
                    background: run.id === selectedRunId ? '#eff6ff' : undefined,
                  }}
                >
                  <td style={{ padding: 'var(--space-2)', whiteSpace: 'nowrap' }}>
                    {new Date(run.created_at).toLocaleString('ko-KR')}
                  </td>
                  <td style={{ padding: 'var(--space-2)' }}>
                    {run.version_number ? `v${run.version_number}` : '-'}
                  </td>
                  <td style={{ padding: 'var(--space-2)', maxWidth: 180, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                      {run.collection_id ? <FolderOpen size={13} style={{ color: '#94a3b8', flexShrink: 0 }} /> : <FileText size={13} style={{ color: '#94a3b8', flexShrink: 0 }} />}
                      {run.document_filename ?? (run.collection_id ? '컬렉션' : '-')}
                    </span>
                  </td>
                  <td style={{ padding: 'var(--space-2)' }}>
                    <span className={`krds-badge xsmall ${RUN_STATUS_BADGE[run.status]?.className ?? 'bg-secondary'}`}>
                      {RUN_STATUS_BADGE[run.status]?.label ?? run.status}
                    </span>
                  </td>
                  <td style={{ padding: 'var(--space-2)', color: '#94a3b8', whiteSpace: 'nowrap' }}>
                    {formatDuration(run.started_at, run.completed_at)}
                  </td>
                  <td style={{ padding: 'var(--space-2)', textAlign: 'right', whiteSpace: 'nowrap' }} onClick={(e) => e.stopPropagation()}>
                    {confirmDeleteId === run.id ? (
                      <span style={{ display: 'inline-flex', gap: 'var(--space-1)', alignItems: 'center' }}>
                        <button
                          type="button"
                          onClick={async () => {
                            if (!workflowId) return
                            await deleteRun.mutateAsync({ workflowId, runId: run.id })
                            setConfirmDeleteId(null)
                            if (selectedRunId === run.id) setSelectedRunId(null)
                          }}
                          disabled={deleteRun.isPending}
                          className="krds-btn xsmall primary"
                        >확인</button>
                        <button type="button" onClick={() => setConfirmDeleteId(null)} className="krds-btn xsmall secondary">취소</button>
                      </span>
                    ) : (
                      <span style={{ display: 'inline-flex', gap: 'var(--space-1)' }}>
                        <button
                          type="button"
                          onClick={() => handleExport(run.id)}
                          className="krds-btn xsmall text icon-btn accent"
                          title="결과 내보내기 (JSON)"
                          aria-label="결과 내보내기"
                        >
                          <Download size={13} />
                        </button>
                        <button
                          type="button"
                          onClick={() => setConfirmDeleteId(run.id)}
                          className="krds-btn xsmall text icon-btn danger"
                          title="실행 기록 삭제"
                          aria-label="실행 기록 삭제"
                          disabled={run.status === 'QUEUED' || run.status === 'RUNNING'}
                        >
                          <Trash2 size={13} />
                        </button>
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <div style={{
            border: '1px solid #e2e8f0', borderRadius: 'var(--radius-lg)',
            padding: 'var(--space-4)', minHeight: 200,
          }}>
            {!selectedRunId && (
              <p style={{ margin: 0, color: '#94a3b8', fontSize: 13, textAlign: 'center', paddingTop: 'var(--space-6)' }}>
                실행 기록을 선택하면 변경 사항과 블록별 결과를 확인할 수 있습니다.
              </p>
            )}

            {selectedRunId && runDetail && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
                {runDetail.run.error_message && (
                  <div style={{
                    background: '#fef2f2', border: '1px solid #fecaca', color: '#b91c1c',
                    borderRadius: 'var(--radius-sm)', padding: 'var(--space-2)', fontSize: 12,
                  }}>
                    {runDetail.run.error_message}
                  </div>
                )}

                <div>
                  <h3 style={{ fontSize: 14, fontWeight: 700, margin: '0 0 var(--space-2)' }}>
                    이 실행이 바꾼 것
                  </h3>
                  {changes.length ? (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
                      {changes.map((c, i) => <ChangeView key={`${c.field}-${i}`} change={c} />)}
                    </div>
                  ) : (
                    <p style={{ margin: 0, fontSize: 12, color: '#94a3b8' }}>
                      문서에 반영된 변경이 없습니다 (변경 기록은 이 기능 추가 이후의 실행부터 남습니다).
                    </p>
                  )}
                </div>

                <div>
                  <h3 style={{ fontSize: 14, fontWeight: 700, margin: '0 0 var(--space-2)' }}>블록별 실행 결과</h3>
                  <StepTimeline steps={steps} blockName={blockName} />
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
