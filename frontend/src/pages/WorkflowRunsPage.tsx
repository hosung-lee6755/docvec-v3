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
import {
  Alert, Badge, Button, EmptyState, IconButton, Page, PageHeader, Stat, StatStrip,
} from '../components/ui'
import type { BadgeTone } from '../components/ui/classes'
import '../styles/screens/pipeline.css'

const RUN_STATUS_BADGE: Record<string, { label: string; tone: BadgeTone }> = {
  QUEUED: { label: '대기 중', tone: 'neutral' },
  RUNNING: { label: '실행 중', tone: 'info' },
  COMPLETED: { label: '완료', tone: 'success' },
  FAILED: { label: '실패', tone: 'danger' },
  CANCELLED: { label: '취소됨', tone: 'neutral' },
  PENDING: { label: '대기', tone: 'neutral' },
  WAITING_REVIEW: { label: '검토 대기', tone: 'warning' },
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
        <strong style={{ fontSize: 'var(--text-xs)' }}>{label}</strong>
        <div className="pipeline-tag-list">
          {change.after.map((tag) => {
            const isNew = !before.has(String(tag).toLowerCase())
            return (
              <Badge
                key={String(tag)}
                tone={isNew ? 'info' : 'neutral'}
                title={isNew ? '이번 실행에서 추가됨' : '기존에 있던 항목'}
              >
                {isNew ? '+ ' : ''}{String(tag)}
              </Badge>
            )
          })}
        </div>
      </div>
    )
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <strong style={{ fontSize: 'var(--text-xs)' }}>{label}</strong>
      <div className="pipeline-change-pair">
        <div className="pipeline-change-box pipeline-change-box--before">
          <div className="pipeline-change-box__label">변경 전</div>
          {change.before ? String(change.before) : <span className="ds-cell-muted">(없음)</span>}
        </div>
        <div className="pipeline-change-box pipeline-change-box--after">
          <div className="pipeline-change-box__label">변경 후</div>
          {change.after ? String(change.after) : <span className="ds-cell-muted">(없음)</span>}
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
  const { data: runDetail, error: runDetailError, isLoading: isRunDetailLoading } = useWorkflowRun(selectedRunId)

  const selectedRun = runsData?.items.find((r) => r.id === selectedRunId) ?? null
  // Block names come from the graph of the version the run executed.
  const { data: graph } = useWorkflowGraph(workflowId ?? null, selectedRun?.version_id ?? null)

  const basePath = projectId ? `/projects/${projectId}` : ''
  const runItems = runsData?.items ?? []
  const failedCount = runItems.filter((r) => r.status === 'FAILED').length
  const completedCount = runItems.filter((r) => r.status === 'COMPLETED').length
  const activeCount = runItems.filter((r) => r.status === 'QUEUED' || r.status === 'RUNNING').length
  const reviewCount = runItems.filter((r) => r.status === 'WAITING_REVIEW').length

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
    <Page>
      <PageHeader
        title={`실행 이력${workflow ? ` — ${workflow.name}` : ''}`}
        actions={(
          <Button
            variant="ghost"
            icon={<ArrowLeft size={14} aria-hidden="true" />}
            onClick={() => navigate(`${basePath}/workflows/${workflowId}/edit`)}
          >
            에디터로
          </Button>
        )}
      />

      {!!runItems.length && (
        <StatStrip label="실행 요약">
          <Stat label="전체" value={runItems.length} />
          <Stat label="완료" value={completedCount} tone="success" />
          <Stat label="실패" value={failedCount} tone={failedCount > 0 ? 'danger' : 'default'} />
          <Stat label="검토 대기" value={reviewCount} tone={reviewCount > 0 ? 'warning' : 'default'} />
          <Stat label="진행 중" value={activeCount} />
        </StatStrip>
      )}

      {!runItems.length && (
        <div style={{ padding: 'var(--space-4) var(--space-5)' }}>
          <EmptyState title="아직 실행 이력이 없습니다." description="에디터에서 게시된 버전을 실행해 보세요." />
        </div>
      )}

      {!!runItems.length && (
        <div className="pipeline-runs-split">
          <div className="ds-table-wrap">
            <table className="ds-table ds-table--compact">
              <thead>
                <tr>
                  <th>실행 시각</th>
                  <th>버전</th>
                  <th>대상</th>
                  <th>상태</th>
                  <th>소요 시간</th>
                  <th aria-label="작업" />
                </tr>
              </thead>
              <tbody>
                {runItems.map((run) => {
                  const statusBadge = RUN_STATUS_BADGE[run.status] ?? { label: run.status, tone: 'neutral' as const }
                  return (
                    <tr
                      key={run.id}
                      className={[
                        run.status === 'FAILED' ? 'is-danger' : '',
                        run.id === selectedRunId ? 'is-selected' : '',
                      ].filter(Boolean).join(' ')}
                      onClick={() => setSelectedRunId(run.id)}
                      style={{ cursor: 'pointer' }}
                    >
                      <td style={{ whiteSpace: 'nowrap' }}>
                        {new Date(run.created_at).toLocaleString('ko-KR')}
                      </td>
                      <td className="pipeline-cell-mono">
                        {run.version_number ? `v${run.version_number}` : '-'}
                      </td>
                      <td style={{ maxWidth: 180, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                          {run.collection_id
                            ? <FolderOpen size={13} className="ds-cell-muted" style={{ flexShrink: 0 }} aria-hidden="true" />
                            : <FileText size={13} className="ds-cell-muted" style={{ flexShrink: 0 }} aria-hidden="true" />}
                          {run.document_filename ?? (run.collection_id ? '컬렉션' : '-')}
                        </span>
                      </td>
                      <td>
                        <Badge tone={statusBadge.tone} hasDot>{statusBadge.label}</Badge>
                      </td>
                      <td className="ds-cell-muted" style={{ whiteSpace: 'nowrap' }}>
                        {formatDuration(run.started_at, run.completed_at)}
                      </td>
                      <td style={{ textAlign: 'right', whiteSpace: 'nowrap' }} onClick={(e) => e.stopPropagation()}>
                        {confirmDeleteId === run.id ? (
                          <span className="pipeline-confirm">
                            <Button
                              variant="danger-solid"
                              size="sm"
                              disabled={deleteRun.isPending}
                              onClick={async () => {
                                if (!workflowId) return
                                await deleteRun.mutateAsync({ workflowId, runId: run.id })
                                setConfirmDeleteId(null)
                                if (selectedRunId === run.id) setSelectedRunId(null)
                              }}
                            >
                              확인
                            </Button>
                            <Button variant="ghost" size="sm" onClick={() => setConfirmDeleteId(null)}>취소</Button>
                          </span>
                        ) : (
                          <span style={{ display: 'inline-flex', gap: 'var(--space-1)' }}>
                            <IconButton label="결과 내보내기" title="결과 내보내기 (JSON)" onClick={() => handleExport(run.id)}>
                              <Download size={13} aria-hidden="true" />
                            </IconButton>
                            <IconButton
                              tone="danger"
                              label="실행 기록 삭제"
                              title="실행 기록 삭제"
                              onClick={() => setConfirmDeleteId(run.id)}
                              disabled={run.status === 'QUEUED' || run.status === 'RUNNING'}
                            >
                              <Trash2 size={13} aria-hidden="true" />
                            </IconButton>
                          </span>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          <aside className="pipeline-runs-detail" aria-label="실행 상세">
            {!selectedRunId && (
              <p className="pipeline-runs-detail__empty">
                실행 기록을 선택하면 변경 사항과 블록별 결과를 확인할 수 있습니다.
              </p>
            )}

            {selectedRunId && isRunDetailLoading && (
              <p className="pipeline-runs-detail__empty">실행 상세를 불러오는 중입니다.</p>
            )}
            {selectedRunId && runDetailError && (
              <Alert tone="warning">
                {(runDetailError as { response?: { status?: number } }).response?.status === 403
                  ? '이 실행의 상세를 볼 권한이 없습니다. 대상 문서가 없거나 접근할 수 없는 실행입니다.'
                  : '실행 상세를 불러오지 못했습니다. 잠시 후 다시 시도하세요.'}
              </Alert>
            )}

            {selectedRunId && runDetail && (
              <>
                {runDetail.run.error_message && (
                  <Alert tone="danger">{runDetail.run.error_message}</Alert>
                )}

                <div className="pipeline-runs-detail__section" style={{ marginTop: runDetail.run.error_message ? 'var(--space-4)' : 0 }}>
                  <h2 className="pipeline-runs-detail__title">이 실행이 바꾼 것</h2>
                  {changes.length ? (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
                      {changes.map((c, i) => <ChangeView key={`${c.field}-${i}`} change={c} />)}
                    </div>
                  ) : (
                    <p className="ds-cell-muted" style={{ margin: 0, fontSize: 'var(--text-xs)' }}>
                      문서에 반영된 변경이 없습니다 (변경 기록은 이 기능 추가 이후의 실행부터 남습니다).
                    </p>
                  )}
                </div>

                <div className="pipeline-runs-detail__section">
                  <h2 className="pipeline-runs-detail__title">블록별 실행 결과</h2>
                  <StepTimeline steps={steps} blockName={blockName} />
                </div>
              </>
            )}
          </aside>
        </div>
      )}
    </Page>
  )
}
