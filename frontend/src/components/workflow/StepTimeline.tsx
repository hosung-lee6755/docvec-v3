import type { ReactNode } from 'react'
import { CheckCircle2, Loader2, XCircle } from 'lucide-react'
import type { WorkflowRunStep } from '../../hooks/useWorkflows'
import { Badge } from '../ui'
import { explainFailure } from '../../lib/apiError'
import '../../styles/screens/pipeline.css'

const STEP_STATUS_LABELS: Record<string, string> = {
  PENDING: '대기', RUNNING: '실행 중', COMPLETED: '완료', FAILED: '실패', SKIPPED: '건너뜀',
}

interface StepTimelineProps {
  steps: WorkflowRunStep[]
  // WorkflowRunsPage still resolves names from the version graph (blocks may
  // predate this endpoint returning `label`); the 처리 이력 tab can omit this
  // and rely on step.label (server-resolved from the block instance/registry).
  blockName?: (blockInstanceId: string) => string
  // Only the 처리 이력 tab passes this (renders "이 블록부터 재처리" per step) —
  // WorkflowRunsPage does not, per Phase 9 scope (그 페이지 자체 개편은 9d로 미룸).
  renderStepActions?: (step: WorkflowRunStep) => ReactNode
}

function StepIcon({ status }: { status: string }) {
  if (status === 'COMPLETED') return <CheckCircle2 size={14} className="wf-step__icon--success" aria-hidden="true" />
  if (status === 'FAILED') return <XCircle size={14} className="wf-step__icon--danger" aria-hidden="true" />
  if (status === 'PENDING' || status === 'RUNNING') {
    return <Loader2 size={14} className="wf-step__icon--primary pipeline-spin" aria-hidden="true" />
  }
  return null
}

export default function StepTimeline({ steps, blockName, renderStepActions }: StepTimelineProps) {
  return (
    <div className="wf-steps">
      {steps.map((step) => {
        const output = step.output
          ? Object.fromEntries(Object.entries(step.output).filter(([k]) => k !== 'text' && k !== 'changes'))
          : null
        return (
          <div key={step.id} className="wf-step">
            <div className="wf-step__head">
              <StepIcon status={step.status} />
              <span className="wf-step__name">
                {step.label ?? blockName?.(step.block_instance_id) ?? step.block_instance_id.slice(0, 8)}
              </span>
              <span className="wf-step__status">{STEP_STATUS_LABELS[step.status] ?? step.status}</span>
              {step.cached && (
                <Badge tone="neutral" title="이전 실행 결과를 그대로 재사용함">캐시</Badge>
              )}
              {renderStepActions && step.status === 'COMPLETED' && (
                <span style={{ marginLeft: 'auto' }}>{renderStepActions(step)}</span>
              )}
            </div>
            {step.error_message && (
              <div style={{ fontSize: 'var(--text-xs)', color: 'var(--color-danger)' }}>{explainFailure(step.error_message)}</div>
            )}
            {!!step.warnings?.length && (
              <div style={{ fontSize: 'var(--text-xs)', color: 'var(--color-warning-text)' }}>
                {step.warnings.join(' · ')}
              </div>
            )}
            {output && Object.keys(output).length > 0 && (
              <pre style={{
                margin: 0, fontSize: 'var(--text-xs)', whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                color: 'var(--color-text-secondary)', maxHeight: 120, overflow: 'auto', fontFamily: 'var(--font-mono)',
              }}>
                {JSON.stringify(output, null, 2)}
              </pre>
            )}
          </div>
        )
      })}
    </div>
  )
}
