import { RUN_STATUS_BADGE, RUN_TRIGGER_LABELS } from './documentDetailHelpers'
import StepTimeline from '../workflow/StepTimeline'
import type { DocumentRunsResult } from '../../hooks/useDocumentRuns'
import type { WorkflowRunStep } from '../../hooks/useWorkflows'

interface HistoryTabProps {
  runsData: DocumentRunsResult | undefined
  selectedRunId: string | null
  historyRunDetail: { steps: WorkflowRunStep[] } | undefined
  onSelectedRunIdChange: (id: string) => void
  onReprocessFromHistory: (blockInstanceId: string) => void
}

export default function HistoryTab({
  runsData,
  selectedRunId,
  historyRunDetail,
  onSelectedRunIdChange,
  onReprocessFromHistory,
}: HistoryTabProps) {
  if (!runsData?.runs.length) {
    return (
      <p style={{ color: 'var(--color-text-muted)', fontSize: 13, margin: 0 }}>
        처리 이력이 없습니다.
      </p>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        {runsData.runs.map((run) => (
          <button
            key={run.id}
            onClick={() => onSelectedRunIdChange(run.id)}
            style={{
              display: 'flex', alignItems: 'center', gap: 'var(--space-2)', textAlign: 'left',
              padding: 'var(--space-1) var(--space-2)', fontSize: 12, border: '1px solid #e2e8f0',
              borderRadius: 'var(--radius-sm)', cursor: 'pointer',
              background: run.id === selectedRunId ? '#eff6ff' : '#fff',
            }}
          >
            <span className={`krds-badge xsmall ${RUN_STATUS_BADGE[run.status] ?? 'bg-gray'}`}>
              {run.status}
            </span>
            <span>{RUN_TRIGGER_LABELS[run.trigger] ?? run.trigger}</span>
            <span style={{ color: 'var(--color-text-muted)' }}>
              {run.started_at ? new Date(run.started_at).toLocaleString('ko-KR') : '-'}
            </span>
            {run.dictionary_version != null && (
              <span style={{ color: 'var(--color-text-muted)' }}>사전 v{run.dictionary_version}</span>
            )}
          </button>
        ))}
      </div>
      {historyRunDetail && (
        <StepTimeline
          steps={historyRunDetail.steps}
          renderStepActions={(step) => (
            <button
              onClick={() => onReprocessFromHistory(step.block_instance_id)}
              className="krds-btn text xsmall"
              style={{ cursor: 'pointer' }}
            >
              이 블록부터 재처리
            </button>
          )}
        />
      )}
    </div>
  )
}
